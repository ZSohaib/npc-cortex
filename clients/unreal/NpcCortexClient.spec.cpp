// Automation spec for the Unreal client (pure helpers; no server needed).
// Run from the Session Frontend: NpcCortex.Client.
// One live integration test is tagged [Live] and needs a BridgeServer on
// 127.0.0.1:8471 (see examples/bridge_server.py).
#include "Misc/AutomationTest.h"
#include "NpcCortexClient.h"

BEGIN_DEFINE_SPEC(FNpcCortexClientSpec, "NpcCortex.Client",
                  EAutomationTestFlags::ProductFilter | EAutomationTestFlags::ApplicationContextMask)
END_DEFINE_SPEC(FNpcCortexClientSpec)

void FNpcCortexClientSpec::Define()
{
    Describe("Mapping", [this]()
    {
        It("maps FVector to position by identity on components", [this]()
        {
            TestEqual("vec", UNpcCortexClient::VecToPosition(FVector(1, 2, 3)),
                      TArray<double>{1.0, 2.0, 3.0});
        });

        It("maps a 3-array back to FVector", [this]()
        {
            TestEqual("fvec", UNpcCortexClient::PositionToFVector({4.0, 5.0, 6.0}),
                      FVector(4, 5, 6));
        });

        It("defaults a missing Z to 0", [this]()
        {
            TestEqual("fvec2d", UNpcCortexClient::PositionToFVector({4.0, 5.0}),
                      FVector(4, 5, 0));
        });
    });

    Describe("Submit body", [this]()
    {
        It("carries the npc id and text", [this]()
        {
            const FString Body = UNpcCortexClient::BuildSubmitBody(
                TEXT("direct_message"), TEXT("n1"), TEXT("p1"), TEXT("hello"));
            TestTrue("npc", Body.Contains(TEXT("n1")));
            TestTrue("text", Body.Contains(TEXT("hello")));
        });

        It("encodes missing speaker/text as null", [this]()
        {
            const FString Body = UNpcCortexClient::BuildSubmitBody(
                TEXT("tick"), TEXT("n1"), TEXT(""), TEXT(""));
            TestTrue("speaker null", Body.Contains(TEXT("\"speaker_id\":null")));
            TestTrue("text null", Body.Contains(TEXT("\"text\":null")));
        });
    });

    Describe("Pump response", [this]()
    {
        It("parses the resolved count", [this]()
        {
            TestEqual("resolved",
                      UNpcCortexClient::ParsePumpResponse(TEXT("{\"resolved\":2}")), 2);
        });

        It("returns -1 when malformed", [this]()
        {
            TestEqual("bad", UNpcCortexClient::ParsePumpResponse(TEXT("nope")), -1);
        });
    });
}
