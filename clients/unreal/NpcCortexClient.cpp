// NpcCortexClient implementation.
#include "NpcCortexClient.h"
#include "HttpModule.h"
#include "Interfaces/IHttpResponse.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

void UNpcCortexClient::Init(const FString& InBaseUrl)
{
    BaseUrl = InBaseUrl;
    while (BaseUrl.EndsWith(TEXT("/")))
        BaseUrl.LeftChopInline(1);
}

TArray<double> UNpcCortexClient::VecToPosition(const FVector& V)
{
    return {V.X, V.Y, V.Z};
}

FVector UNpcCortexClient::PositionToFVector(const TArray<double>& P)
{
    const double Z = P.Num() > 2 ? P[2] : 0.0;
    return FVector(P.Num() > 0 ? P[0] : 0.0, P.Num() > 1 ? P[1] : 0.0, Z);
}

FString UNpcCortexClient::BuildSubmitBody(const FString& Kind, const FString& NpcId,
                                          const FString& SpeakerId, const FString& Text)
{
    TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
    Obj->SetStringField(TEXT("kind"), Kind);
    Obj->SetStringField(TEXT("npc_id"), NpcId);
    if (SpeakerId.IsEmpty())
        Obj->SetField(TEXT("speaker_id"), MakeShared<FJsonValueNull>());
    else
        Obj->SetStringField(TEXT("speaker_id"), SpeakerId);
    if (Text.IsEmpty())
        Obj->SetField(TEXT("text"), MakeShared<FJsonValueNull>());
    else
        Obj->SetStringField(TEXT("text"), Text);
    FString Out;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
    FJsonSerializer::Serialize(Obj.ToSharedRef(), Writer);
    return Out;
}

int32 UNpcCortexClient::ParsePumpResponse(const FString& Body)
{
    TSharedPtr<FJsonObject> Obj;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Body);
    if (!FJsonSerializer::Deserialize(Reader, Obj) || !Obj.IsValid())
        return -1;
    int32 Resolved = -1;
    Obj->TryGetNumberField(TEXT("resolved"), Resolved);
    return Resolved;
}

TSharedRef<IHttpRequest> UNpcCortexClient::NewRequest(const FString& Path, const FString& Verb)
{
    TSharedRef<IHttpRequest> Req = FHttpModule::Get().CreateRequest();
    Req->SetURL(BaseUrl + Path);
    Req->SetVerb(Verb);
    Req->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
    return Req;
}

void UNpcCortexClient::Submit(const FString& Kind, const FString& NpcId,
                              const FString& SpeakerId, const FString& Text)
{
    TSharedRef<IHttpRequest> Req = NewRequest(TEXT("/v1/submit"), TEXT("POST"));
    Req->SetContentAsString(BuildSubmitBody(Kind, NpcId, SpeakerId, Text));
    Req->ProcessRequest(); // fire-and-forget; errors surface in the log
}

void UNpcCortexClient::Pump(FNpcPumpDone Completed)
{
    TSharedRef<IHttpRequest> Req = NewRequest(TEXT("/v1/pump"), TEXT("POST"));
    Req->SetContentAsString(TEXT("{}"));
    Req->OnProcessRequestComplete().BindLambda(
        [Completed](FHttpRequestPtr, FHttpResponsePtr Resp, bool bOk)
        {
            int32 Resolved = 0;
            if (bOk && Resp.IsValid() && Resp->GetResponseCode() < 300)
                Resolved = ParsePumpResponse(Resp->GetContentAsString());
            else
                bOk = false;
            Completed.ExecuteIfBound(Resolved, bOk);
        });
    Req->ProcessRequest();
}

void UNpcCortexClient::Actions(int32 Since, FNpcActionsDone Completed)
{
    TSharedRef<IHttpRequest> Req =
        NewRequest(FString::Printf(TEXT("/v1/actions?since=%d"), Since), TEXT("GET"));
    Req->OnProcessRequestComplete().BindLambda(
        [Completed](FHttpRequestPtr, FHttpResponsePtr Resp, bool bOk)
        {
            TArray<FNpcRemoteAction> Out;
            int32 NextSince = 0;
            if (bOk && Resp.IsValid() && Resp->GetResponseCode() < 300)
            {
                TSharedPtr<FJsonObject> Obj;
                TSharedRef<TJsonReader<>> Reader =
                    TJsonReaderFactory<>::Create(Resp->GetContentAsString());
                if (FJsonSerializer::Deserialize(Reader, Obj) && Obj.IsValid())
                {
                    Obj->TryGetNumberField(TEXT("next_since"), NextSince);
                    const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
                    if (Obj->TryGetArrayField(TEXT("actions"), Arr))
                    {
                        for (const TSharedPtr<FJsonValue>& V : *Arr)
                        {
                            const TSharedPtr<FJsonObject> A = V->AsObject();
                            if (!A.IsValid())
                                continue;
                            FNpcRemoteAction E;
                            A->TryGetNumberField(TEXT("seq"), E.Seq);
                            A->TryGetStringField(TEXT("handle"), E.Handle);
                            A->TryGetStringField(TEXT("actor_id"), E.ActorId);
                            A->TryGetStringField(TEXT("npc_id"), E.NpcId);
                            A->TryGetStringField(TEXT("name"), E.Name);
                            A->TryGetBoolField(TEXT("broadcast"), E.bBroadcast);
                            const TSharedPtr<FJsonObject>* Params = nullptr;
                            if (A->TryGetObjectField(TEXT("parameters"), Params))
                            {
                                for (const auto& KV : (*Params)->Values)
                                {
                                    FString Encoded;
                                    TSharedRef<TJsonWriter<>> W =
                                        TJsonWriterFactory<>::Create(&Encoded);
                                    FJsonSerializer::Serialize(KV.Value.ToSharedRef(), W);
                                    E.Parameters.Add(KV.Key, Encoded);
                                }
                            }
                            Out.Add(MoveTemp(E));
                        }
                    }
                }
            }
            Completed.ExecuteIfBound(Out, NextSince);
        });
    Req->ProcessRequest();
}

void UNpcCortexClient::Sync(const FString& PlayerId, const FVector& PlayerPos,
                            const FString& NpcId, const FVector& NpcPos, double Horizon)
{
    auto ToArray = [](const FVector& V)
    {
        TArray<TSharedPtr<FJsonValue>> A;
        A.Add(MakeShared<FJsonValueNumber>(V.X));
        A.Add(MakeShared<FJsonValueNumber>(V.Y));
        A.Add(MakeShared<FJsonValueNumber>(V.Z));
        return A;
    };
    TSharedPtr<FJsonObject> P = MakeShared<FJsonObject>();
    P->SetStringField(TEXT("id"), PlayerId);
    P->SetArrayField(TEXT("position"), ToArray(PlayerPos));
    P->SetNumberField(TEXT("horizon"), Horizon);
    TSharedPtr<FJsonObject> N = MakeShared<FJsonObject>();
    N->SetStringField(TEXT("id"), NpcId);
    N->SetArrayField(TEXT("position"), ToArray(NpcPos));
    N->SetNumberField(TEXT("horizon"), Horizon);
    TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
    TArray<TSharedPtr<FJsonValue>> PA, NA;
    PA.Add(MakeShared<FJsonValueObject>(P));
    NA.Add(MakeShared<FJsonValueObject>(N));
    Obj->SetArrayField(TEXT("players"), PA);
    Obj->SetArrayField(TEXT("npcs"), NA);
    FString Out;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
    FJsonSerializer::Serialize(Obj.ToSharedRef(), Writer);
    TSharedRef<IHttpRequest> Req = NewRequest(TEXT("/v1/sync"), TEXT("POST"));
    Req->SetContentAsString(Out);
    Req->ProcessRequest();
}

void UNpcCortexClient::Knowledge(const FString& NpcId, const FString& ActorId,
                                    int32 Limit, TFunction<void(const FString&)> Completed)
{
    FString Path = FString::Printf(TEXT("/v1/knowledge?npc_id=%s"), *NpcId);
    if (!ActorId.IsEmpty())
        Path += FString::Printf(TEXT("&actor_id=%s"), *ActorId);
    if (Limit >= 0)
        Path += FString::Printf(TEXT("&limit=%d"), Limit);
    TSharedRef<IHttpRequest> Req = NewRequest(Path, TEXT("GET"));
    Req->OnProcessRequestComplete().BindLambda(
        [Completed](FHttpRequestPtr, FHttpResponsePtr Resp, bool bOk)
        {
            Completed(bOk && Resp.IsValid() ? Resp->GetContentAsString()
                                            : FString(TEXT("{\"history\":[],\"acquaintances\":{}}")));
        });
    Req->ProcessRequest();
}

void UNpcCortexClient::Surroundings(const FString& NpcId, double Radius,
                                    TFunction<void(const FString&)> Completed)
{
    TSharedRef<IHttpRequest> Req = NewRequest(
        FString::Printf(TEXT("/v1/surroundings?npc_id=%s&radius=%f"), *NpcId, Radius),
        TEXT("GET"));
    Req->OnProcessRequestComplete().BindLambda(
        [Completed](FHttpRequestPtr, FHttpResponsePtr Resp, bool bOk)
        {
            Completed(bOk && Resp.IsValid() ? Resp->GetContentAsString()
                                            : FString(TEXT("{\"places\":[]}")));
        });
    Req->ProcessRequest();
}
