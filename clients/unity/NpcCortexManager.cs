// NpcCortexManager: example MonoBehaviour driving one bridge server.
// Each frame: sync dirty transforms -> pump -> drain actions/deliveries.
// Attach to a GameObject, set BridgeUrl, and register Npc/Player entries.

using System.Collections.Generic;
using UnityEngine;

namespace NpcCortex
{
    [AddComponentMenu("NPC Cortex/Bridge Manager")]
    public sealed class NpcCortexManager : MonoBehaviour
    {
        [Tooltip("Base URL of the BridgeServer, e.g. http://127.0.0.1:8471")]
        public string BridgeUrl = "http://127.0.0.1:8471";

        [Tooltip("Call /v1/sync every frame (cheap) or only when dirty.")]
        public bool SyncEveryFrame = true;

        [System.Serializable]
        public sealed class TrackedPlayer
        {
            public string Id;
            public Transform Transform;
            public float Horizon = 10f;
        }

        [System.Serializable]
        public sealed class TrackedNpc
        {
            public string Id;
            public Transform Transform;
            public float Horizon = 10f;
        }

        public List<TrackedPlayer> Players = new();
        public List<TrackedNpc> Npcs = new();

        public NpcCortexClient Client { get; private set; }
        public System.Action<RemoteAction> OnRemoteAction = _ => { };
        public System.Action<string, string> OnSpeech = (_, _) => { };

        private int _actionCursor;
        private int _deliveredCursor;
        private bool _pumping;

        private void Awake()
        {
            Client = new NpcCortexClient(BridgeUrl);
        }

        private void OnDestroy()
        {
            Client?.Dispose();
            Client = null;
        }

        private async void Update()
        {
            if (_pumping) return; // one in-flight frame; never stall Update
            _pumping = true;
            try
            {
                if (SyncEveryFrame) await SyncTransforms();
                await Client.Pump();
                var (actions, nextA) = await Client.Actions(_actionCursor);
                _actionCursor = nextA;
                foreach (var action in actions) OnRemoteAction(action);
                var (delivered, nextD) = await Client.Delivered(_deliveredCursor);
                _deliveredCursor = nextD;
                foreach (var (playerId, text) in delivered) OnSpeech(playerId, text);
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[npc-cortex] frame skipped: {e.Message}");
            }
            finally { _pumping = false; }
        }

        public async System.Threading.Tasks.Task SyncTransforms()
        {
            var players = new List<NpcCortexClient.SyncPlayer>();
            foreach (var p in Players)
            {
                if (p.Transform == null) continue;
                var v = p.Transform.position;
                players.Add(new NpcCortexClient.SyncPlayer
                    { Id = p.Id, Position = new[] { v.x, v.y, v.z }, Horizon = p.Horizon });
            }
            var npcs = new List<NpcCortexClient.SyncNpc>();
            foreach (var n in Npcs)
            {
                if (n.Transform == null) continue;
                var v = n.Transform.position;
                npcs.Add(new NpcCortexClient.SyncNpc
                    { Id = n.Id, Position = new[] { v.x, v.y, v.z }, Horizon = n.Horizon });
            }
            await Client.Sync(players, npcs);
        }

        /// <summary>Send a line of dialogue from a player to an NPC.</summary>
        public async void SayTo(string npcId, string playerId, string text)
        {
            try { await Client.Submit("direct_message", npcId, playerId, text); }
            catch (System.Exception e) { Debug.LogWarning($"[npc-cortex] submit: {e.Message}"); }
        }
    }
}
