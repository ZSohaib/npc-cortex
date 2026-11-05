// NpcCortexClient: C# client for the npc-cortex HTTP bridge (docs/PROTOCOL.md).
// Mirrors npc_cortex.client.RemoteBridge method for method.
// Requires Unity 2021+ (.NET Standard 2.1 for System.Text.Json) or any
// modern .NET. No UnityEngine dependency: usable from plain C# tools too.

using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;

namespace NpcCortex
{
    public sealed class BridgeOverloadedException : Exception
    {
        public BridgeOverloadedException(string detail) : base(detail) { }
    }

    public sealed class BridgeClosedException : Exception
    {
        public BridgeClosedException(string detail) : base(detail) { }
    }

    public sealed class BridgeException : Exception
    {
        public BridgeException(string message) : base(message) { }
    }

    // -- DTOs ---------------------------------------------------------

    [Serializable]
    public sealed class Observation
    {
        [JsonPropertyName("handle")] public string Handle;
        [JsonPropertyName("actor_id")] public string ActorId;
        [JsonPropertyName("action")] public string Action;
        [JsonPropertyName("phase")] public string Phase;
    }

    [Serializable]
    public sealed class MemoryEntry
    {
        [JsonPropertyName("actor_id")] public string ActorId;
        [JsonPropertyName("action")] public string Action;
        [JsonPropertyName("outcome")] public string Outcome;
    }

    [Serializable]
    public sealed class Memory
    {
        [JsonPropertyName("players")] public List<MemoryEntry> Players = new();
        [JsonPropertyName("npcs")] public List<MemoryEntry> Npcs = new();
    }

    [Serializable]
    public sealed class AuditRecord
    {
        [JsonPropertyName("kind")] public string Kind;
        [JsonPropertyName("npc_id")] public string NpcId;
        [JsonPropertyName("event_kind")] public string EventKind;
        [JsonPropertyName("detail")] public string Detail;
    }

    [Serializable]
    public sealed class RemoteAction
    {
        [JsonPropertyName("seq")] public int Seq;
        [JsonPropertyName("handle")] public string Handle;
        [JsonPropertyName("actor_id")] public string ActorId;
        [JsonPropertyName("npc_id")] public string NpcId; // null for engagements
        [JsonPropertyName("name")] public string Name;
        [JsonPropertyName("parameters")] public Dictionary<string, JsonElement> Parameters = new();
        [JsonPropertyName("broadcast")] public bool Broadcast;
    }

    // -- client ---------------------------------------------------------

    /// <summary>
    /// Speaks /v1/* to a BridgeServer. One instance per server; safe for
    /// concurrent use. Coordinate convention: Vector3(x, y, z) maps to
    /// [x, y, z] (identity on components, see adapters/unity.py).
    /// </summary>
    public sealed class NpcCortexClient : IDisposable
    {
        private readonly HttpClient _http;
        private readonly JsonSerializerOptions _json = new()
        {
            PropertyNamingPolicy = null,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            IncludeFields = true,
        };

        public string BaseUrl { get; }

        public NpcCortexClient(string baseUrl, TimeSpan? timeout = null)
        {
            BaseUrl = baseUrl.TrimEnd('/');
            _http = new HttpClient { Timeout = timeout ?? TimeSpan.FromSeconds(10) };
        }

        public void Dispose() => _http.Dispose();

        private async Task<T> Post<T>(string path, object body)
        {
            var payload = new StringContent(
                JsonSerializer.Serialize(body, _json), Encoding.UTF8, "application/json");
            using var resp = await _http.PostAsync(BaseUrl + path, payload).ConfigureAwait(false);
            return await Read<T>(resp).ConfigureAwait(false);
        }

        private async Task<T> Get<T>(string path)
        {
            using var resp = await _http.GetAsync(BaseUrl + path).ConfigureAwait(false);
            return await Read<T>(resp).ConfigureAwait(false);
        }

        private async Task<T> Read<T>(HttpResponseMessage resp)
        {
            var text = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
            if (resp.IsSuccessStatusCode)
                return JsonSerializer.Deserialize<T>(text, _json);
            string name = "", detail = "";
            try
            {
                using var doc = JsonDocument.Parse(text);
                name = doc.RootElement.GetProperty("error").GetString() ?? "";
                detail = doc.RootElement.GetProperty("detail").GetString() ?? "";
            }
            catch (Exception) { /* fall through to generic error */ }
            if (resp.StatusCode == (HttpStatusCode)429 || name == "Overloaded")
                throw new BridgeOverloadedException(detail);
            if (resp.StatusCode == HttpStatusCode.Conflict || name == "Closed")
                throw new BridgeClosedException(detail);
            throw new BridgeException($"{name}: {detail}");
        }

        // -- runtime mirror ---------------------------------------------

        public async Task<Dictionary<string, JsonElement>> Health() =>
            await Get<Dictionary<string, JsonElement>>("/v1/health").ConfigureAwait(false);

        public async Task Submit(string kind, string npcId, string speakerId = null, string text = null)
        {
            await Post<JsonElement>("/v1/submit", new Dictionary<string, object>
            {
                ["kind"] = kind, ["npc_id"] = npcId,
                ["speaker_id"] = speakerId, ["text"] = text,
            }).ConfigureAwait(false);
        }

        public async Task<int> Pump()
        {
            var doc = await Post<JsonElement>("/v1/pump", new { }).ConfigureAwait(false);
            return doc.GetProperty("resolved").GetInt32();
        }

        public async Task<string> Engage(string playerId, string name,
            Dictionary<string, object> parameters, float duration)
        {
            var doc = await Post<JsonElement>("/v1/engage", new Dictionary<string, object>
            {
                ["player_id"] = playerId, ["name"] = name,
                ["parameters"] = parameters, ["duration"] = duration,
            }).ConfigureAwait(false);
            return doc.GetProperty("handle").GetString();
        }

        public async Task Cancel(string handle)
        {
            await Post<JsonElement>("/v1/cancel",
                new Dictionary<string, object> { ["handle"] = handle }).ConfigureAwait(false);
        }

        public async Task<List<Observation>> Observations(string characterId) =>
            (await Get<JsonElement>("/v1/observations?character_id=" + Uri.EscapeDataString(characterId))
                .ConfigureAwait(false))
            .GetProperty("records").Deserialize<List<Observation>>(_json);

        public async Task<Memory> Memory(string npcId) =>
            await Get<Memory>("/v1/memory?npc_id=" + Uri.EscapeDataString(npcId)).ConfigureAwait(false);

        [Serializable]
        public sealed class NearbyPlace
        {
            [JsonPropertyName("id")] public string Id;
            [JsonPropertyName("kind")] public string Kind;
            [JsonPropertyName("distance")] public double Distance;
            [JsonPropertyName("description")] public string Description;
            [JsonPropertyName("public")] public bool Public;
        }

        public async Task<List<NearbyPlace>> Surroundings(string npcId, float radius = 20f) =>
            (await Get<JsonElement>($"/v1/surroundings?npc_id={Uri.EscapeDataString(npcId)}&radius={radius}")
                .ConfigureAwait(false))
            .GetProperty("places").Deserialize<List<NearbyPlace>>(_json);

        public async Task<(List<Observation> History, JsonElement Acquaintances)>
            Knowledge(string npcId, string actorId = null, int? limit = null)
        {
            var path = "/v1/knowledge?npc_id=" + Uri.EscapeDataString(npcId);
            if (actorId != null) path += "&actor_id=" + Uri.EscapeDataString(actorId);
            if (limit != null) path += "&limit=" + limit;
            var doc = await Get<JsonElement>(path).ConfigureAwait(false);
            return (doc.GetProperty("history").Deserialize<List<Observation>>(_json),
                    doc.GetProperty("acquaintances"));
        }

        public async Task<(List<AuditRecord> Records, int NextSince)> Audit(int since = 0)
        {
            var doc = await Get<JsonElement>($"/v1/audit?since={since}").ConfigureAwait(false);
            return (doc.GetProperty("records").Deserialize<List<AuditRecord>>(_json),
                    doc.GetProperty("next_since").GetInt32());
        }

        public async Task<(List<(string PlayerId, string Text)> Delivered, int NextSince)>
            Delivered(int since = 0)
        {
            var doc = await Get<JsonElement>($"/v1/delivered?since={since}").ConfigureAwait(false);
            var out_ = new List<(string, string)>();
            foreach (var pair in doc.GetProperty("delivered").EnumerateArray())
                out_.Add((pair[0].GetString(), pair[1].GetString()));
            return (out_, doc.GetProperty("next_since").GetInt32());
        }

        public async Task<(List<RemoteAction> Actions, int NextSince)> Actions(int since = 0)
        {
            var doc = await Get<JsonElement>($"/v1/actions?since={since}").ConfigureAwait(false);
            return (doc.GetProperty("actions").Deserialize<List<RemoteAction>>(_json),
                    doc.GetProperty("next_since").GetInt32());
        }

        public async Task RegisterAction(string name, Dictionary<string, string> parameters,
            float minImplication = 0f, bool broadcast = false)
        {
            await Post<JsonElement>("/v1/register_action", new Dictionary<string, object>
            {
                ["name"] = name, ["parameters"] = parameters,
                ["min_implication"] = minImplication, ["broadcast"] = broadcast,
            }).ConfigureAwait(false);
        }

        // -- sync helpers -------------------------------------------------

        public sealed class SyncPlayer
        {
            [JsonPropertyName("id")] public string Id;
            [JsonPropertyName("role"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
            public string Role;
            [JsonPropertyName("position"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
            public float[] Position; // [x, y] or [x, y, z]
            [JsonPropertyName("horizon"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
            public float? Horizon;
            [JsonPropertyName("online"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
            public bool? Online;
        }

        public sealed class SyncNpc
        {
            [JsonPropertyName("id")] public string Id;
            [JsonPropertyName("position"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
            public float[] Position;
            [JsonPropertyName("horizon"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
            public float? Horizon;
            [JsonPropertyName("implication"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
            public float? Implication;
        }

        public async Task<JsonElement> Sync(List<SyncPlayer> players = null,
            List<SyncNpc> npcs = null, Dictionary<string, object> worldState = null)
        {
            var body = new Dictionary<string, object>
            {
                ["players"] = players ?? new List<SyncPlayer>(),
                ["npcs"] = npcs ?? new List<SyncNpc>(),
            };
            if (worldState != null) body["world_state"] = worldState;
            return await Post<JsonElement>("/v1/sync", body).ConfigureAwait(false);
        }

        public async Task Close()
        {
            await Post<JsonElement>("/v1/close", new { }).ConfigureAwait(false);
        }
    }
}
