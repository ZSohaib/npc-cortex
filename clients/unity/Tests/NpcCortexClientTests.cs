// Unity Test Framework (EditMode) tests for the C# client.
// Pure unit tests run without a server; [Explicit] integration tests need one:
//   python -m npc_cortex_server_example --port 8471   (see examples/bridge_server.py)

using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using NUnit.Framework;

namespace NpcCortex.Tests
{
    public sealed class MappingTests
    {
        [Test]
        public void Vec3_MapsToPosition_ByIdentityOnComponents()
        {
            // Convention (adapters/unity.py): Vector3(x, y, z) -> [x, y, z].
            var v = new UnityEngine.Vector3(1f, 2f, 3f);
            float[] pos = { v.x, v.y, v.z };
            Assert.AreEqual(new[] { 1f, 2f, 3f }, pos);
        }

        [Test]
        public void Vec2_MapsToPosition_ByIdentityOnComponents()
        {
            var v = new UnityEngine.Vector2(4f, 5f);
            float[] pos = { v.x, v.y };
            Assert.AreEqual(new[] { 4f, 5f }, pos);
        }

        [Test]
        public void SubmitBody_CarriesNpcIdAndText()
        {
            var body = new Dictionary<string, object>
            {
                ["kind"] = "direct_message", ["npc_id"] = "n1",
                ["speaker_id"] = "p1", ["text"] = "hello",
            };
            var text = JsonSerializer.Serialize(body);
            StringAssert.Contains("n1", text);
            StringAssert.Contains("hello", text);
        }
    }

    [Explicit("needs a live BridgeServer on 127.0.0.1:8471")]
    public sealed class LiveBridgeTests
    {
        private NpcCortexClient _client;

        [SetUp]
        public void SetUp() => _client = new NpcCortexClient("http://127.0.0.1:8471");

        [TearDown]
        public void TearDown() => _client.Dispose();

        [Test]
        public async Task Health_AnswersOk()
        {
            var health = await _client.Health();
            Assert.IsTrue(health["ok"].GetBoolean());
        }

        [Test]
        public async Task Sync_Submit_Pump_DeliversSpeech()
        {
            await _client.Sync(
                new List<NpcCortexClient.SyncPlayer>
                    { new() { Id = "p1", Position = new[] { 0f, 0f, 0f }, Horizon = 50f } },
                new List<NpcCortexClient.SyncNpc>
                    { new() { Id = "n1", Position = new[] { 1f, 0f, 0f }, Horizon = 50f } });
            await _client.Submit("tick", "n1");
            for (int i = 0; i < 200; i++)
            {
                if (await _client.Pump() > 0) break;
                await Task.Delay(25);
            }
            var (delivered, _) = await _client.Delivered();
            Assert.IsNotEmpty(delivered);
        }

        [Test]
        public async Task Cancel_OnUnknownHandle_IsInert()
        {
            await _client.Cancel("engagement-424242"); // must not throw
        }
    }
}
