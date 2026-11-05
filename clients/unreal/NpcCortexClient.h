// NpcCortexClient: Unreal C++ client for the npc-cortex HTTP bridge.
// Mirrors npc_cortex.client.RemoteBridge. Requires the HTTP module
// (add "HTTP", "Json", "JsonUtilities" to Build.cs).
#pragma once

#include "CoreMinimal.h"
#include "Interfaces/IHttpRequest.h"
#include "NpcCortexClient.generated.h"

USTRUCT(BlueprintType)
struct FNpcObservation
{
    GENERATED_BODY()
    UPROPERTY(BlueprintReadOnly) FString Handle;
    UPROPERTY(BlueprintReadOnly) FString ActorId;
    UPROPERTY(BlueprintReadOnly) FString Action;
    UPROPERTY(BlueprintReadOnly) FString Phase;
};

USTRUCT(BlueprintType)
struct FNpcMemoryEntry
{
    GENERATED_BODY()
    UPROPERTY(BlueprintReadOnly) FString ActorId;
    UPROPERTY(BlueprintReadOnly) FString Action;
    UPROPERTY(BlueprintReadOnly) FString Outcome;
};

USTRUCT(BlueprintType)
struct FNpcRemoteAction
{
    GENERATED_BODY()
    UPROPERTY(BlueprintReadOnly) int32 Seq = 0;
    UPROPERTY(BlueprintReadOnly) FString Handle;
    UPROPERTY(BlueprintReadOnly) FString ActorId;
    UPROPERTY(BlueprintReadOnly) FString NpcId; // empty for engagements
    UPROPERTY(BlueprintReadOnly) FString Name;
    UPROPERTY(BlueprintReadOnly) TMap<FString, FString> Parameters; // JSON-encoded values
    UPROPERTY(BlueprintReadOnly) bool bBroadcast = false;
};

DECLARE_DELEGATE_TwoParams(FNpcPumpDone, int32 /*Resolved*/, bool /*bOk*/);
DECLARE_DELEGATE_TwoParams(FNpcActionsDone, const TArray<FNpcRemoteAction>&, int32 /*NextSince*/);

/**
 * Speaks /v1/* to a BridgeServer.
 * Coordinate convention: FVector(X, Y, Z) maps to [X, Y, Z] (identity on
 * components, see adapters/unreal.py). Keep one unit scale on both sides
 * (recommended: centimetres) and set horizon in the same units.
 */
UCLASS(BlueprintType)
class UNpcCortexClient : public UObject
{
    GENERATED_BODY()

public:
    void Init(const FString& InBaseUrl);

    // -- pure helpers (unit-tested, no HTTP) ---------------------------

    /** FVector -> protocol [X, Y, Z] array. */
    UFUNCTION(BlueprintPure, Category = "NPC Cortex")
    static TArray<double> VecToPosition(const FVector& V);

    /** Protocol [X, Y(, Z)] array -> FVector (missing Z = 0). */
    UFUNCTION(BlueprintPure, Category = "NPC Cortex")
    static FVector PositionToFVector(const TArray<double>& P);

    /** Build the JSON body for POST /v1/submit. */
    static FString BuildSubmitBody(const FString& Kind, const FString& NpcId,
                                   const FString& SpeakerId, const FString& Text);

    /** Parse a POST /v1/pump response; returns -1 when malformed. */
    static int32 ParsePumpResponse(const FString& Body);

    // -- async HTTP API --------------------------------------------------

    /** Fire-and-forget event submit. */
    void Submit(const FString& Kind, const FString& NpcId,
                const FString& SpeakerId = TEXT(""), const FString& Text = TEXT());

    /** Pump once; Completed fires with (Resolved, bOk). */
    void Pump(FNpcPumpDone Completed);

    /** Poll applied remote actions from Since; Completed fires with (Actions, NextSince). */
    void Actions(int32 Since, FNpcActionsDone Completed);

    /** Upsert one player + one NPC transform (call per frame or when dirty). */
    void Sync(const FString& PlayerId, const FVector& PlayerPos,
              const FString& NpcId, const FVector& NpcPos, double Horizon);

    /** Places near an NPC, nearest first (observable facts only). */
    void Surroundings(const FString& NpcId, double Radius,
                      TFunction<void(const FString& /*Json*/)> Completed);

    /** What NpcId developed about others (history + acquaintances JSON). */
    void Knowledge(const FString& NpcId, const FString& ActorId, int32 Limit,
                   TFunction<void(const FString& /*Json*/)> Completed);

private:
    FString BaseUrl;

    TSharedRef<IHttpRequest> NewRequest(const FString& Path, const FString& Verb);
};
