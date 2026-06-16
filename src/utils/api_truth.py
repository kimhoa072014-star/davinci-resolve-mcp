"""Behaviorally-verified facts about the DaVinci Resolve scripting API.

The Resolve scripting API is under-documented and frequently behaves differently
from its apparent signature: methods live on objects you wouldn't expect, return
values lie, string keys are silently rejected, and some documented-looking calls
don't exist. This module records facts we have *verified against live Resolve* so
agents and code can look the reality up instead of rediscovering it the hard way.

Each entry is a small dict. Grow it opportunistically — every readback recipe and
every fix that uncovers a surprising behavior should add an entry. Facts are
stamped with the Resolve build they were verified on so drift is visible when a
new version ships.
"""
from typing import Any, Dict, List, Optional

VERIFIED_ON = "DaVinci Resolve Studio 21.0.0"

# Each entry: symbol, object, reality, recommended, tags. `signature` optional.
API_TRUTH: List[Dict[str, Any]] = [
    {
        "symbol": "MediaPool.AutoSyncAudio",
        "object": "MediaPool",
        "signature": "(clips, settings) -> bool",
        "reality": "The boolean return does not reflect whether clips actually "
                   "linked, and string enum keys in `settings` are silently "
                   "rejected (the call returns False).",
        "recommended": "Resolve the AUDIO_SYNC_* enum constants via the live "
                       "resolve handle, and verify by reading each clip's "
                       "'Synced Audio' property (see verify_by_readback).",
        "tags": ["unreliable-return", "silent-failure", "audio", "enum"],
    },
    {
        "symbol": "Composition.Paste",
        "object": "Fusion Composition",
        "reality": "Passing tool.SaveSettings()'s in-memory table to Paste() / "
                   "LoadSettings() fails across the Python bridge with an "
                   "OrderedDict/null-argument error and creates no node, while "
                   "reporting nothing useful.",
        "recommended": "Duplicate via AddTool(RegID) + SaveSettings(path)/"
                       "LoadSettings(path) through a temp .setting FILE, which "
                       "round-trips reliably. Identify the new node by name diff.",
        "tags": ["fusion", "bridge", "silent-failure"],
    },
    {
        "symbol": "FlowView.SetPos / FlowView.GetPosTable",
        "object": "Fusion FlowView (comp.CurrentFrame.FlowView)",
        "reality": "Node positions are read/written through the FlowView, not the "
                   "tool. SetPos returns nothing reliable; GetPosTable returns a "
                   "1-indexed table (or dict/tuple depending on bridge).",
        "recommended": "Use comp.CurrentFrame.FlowView.SetPos(tool, x, y); confirm "
                       "with GetPosTable and a liberal position parser.",
        "tags": ["fusion", "unreliable-return"],
    },
    {
        "symbol": "Timeline.GetTimelineByName",
        "object": "Project",
        "reality": "Does not exist. Timelines are looked up by index.",
        "recommended": "Iterate GetTimelineByIndex(1..GetTimelineCount()).",
        "tags": ["missing-method", "timeline"],
    },
    {
        "symbol": "Project render methods (AddRenderJob, SetRenderSettings, ...)",
        "object": "Project",
        "reality": "Render methods live on the Project object, not on a separate "
                   "render-settings interface.",
        "recommended": "Call proj.AddRenderJob(), proj.SetRenderSettings(), "
                       "proj.LoadRenderPreset() directly on the project.",
        "tags": ["render"],
    },
    {
        "symbol": "MediaPoolItem.GetClipProperty('Transcription')",
        "object": "MediaPoolItem",
        "reality": "Returns a PREVIEW of the transcription that ends in an "
                   "ellipsis when the full transcript is longer than the property "
                   "exposes.",
        "recommended": "Treat a trailing ellipsis as truncation (see "
                       "media_pool_item get_transcription's `truncated` flag).",
        "tags": ["transcription", "truncation"],
    },
    {
        "symbol": "ProjectManager.CreateProject (with a dirty Untitled project)",
        "object": "ProjectManager",
        "reality": "Returns None and pops a modal 'Save Current Project' dialog "
                   "when the current unsaved/Untitled project blocks the switch. "
                   "SaveProject() on an Untitled project re-triggers the same modal.",
        "recommended": "CloseProject(current) to discard the untitled project "
                       "without a prompt, then CreateProject; restore with "
                       "LoadProject afterward.",
        "tags": ["project", "modal", "silent-failure"],
    },
    {
        "symbol": "Timeline.InsertFusionCompositionIntoTimeline",
        "object": "Timeline",
        "reality": "Reliable way to obtain a Fusion comp on an otherwise empty "
                   "timeline: it inserts a Fusion composition clip whose comp is "
                   "then reachable via GetFusionCompByIndex(1).",
        "recommended": "Use it (rather than InsertGeneratorIntoTimeline) when you "
                       "need a comp to operate on.",
        "tags": ["fusion", "timeline"],
    },
    {
        "symbol": "subprocess inheriting stdin under the MCP stdio server",
        "object": "(server runtime)",
        "reality": "A child process that inherits stdin can race-read bytes off "
                   "the JSON-RPC protocol stream and corrupt it; capture_output "
                   "redirects only stdout/stderr.",
        "recommended": "Pass stdin=subprocess.DEVNULL on every subprocess that can "
                       "run while serving over stdio.",
        "tags": ["runtime", "stdio", "subprocess"],
    },

    # ── Color page: node graph, grades, LUT/DCTL ──────────────────────────
    # Discovered during a production color-grading workflow on Resolve Studio
    # 20.2.x (an 87-clip graded timeline). Structural facts — which graph/item
    # methods exist — were re-confirmed live on 20.2.1.6; behavioral facts are
    # stamped per entry. New entries carry an optional `verified_on`.
    {
        "symbol": "TimelineItem node graph construction (AddNode / SetNodeInput / connect)",
        "object": "TimelineItem.GetNodeGraph() / Graph",
        "reality": "The node graph is structurally READ-ONLY from scripting. The "
                   "only node methods exposed are GetNumNodes, GetLUT, SetLUT, "
                   "Get/SetNodeCacheMode, GetNodeLabel, GetToolsInNode, "
                   "SetNodeEnabled, ApplyGradeFromDRX, ApplyArriCdlLut, "
                   "ResetAllGrades. There is NO way to add a node, delete a node, "
                   "create parallel/layer/mixer nodes, set blend modes, or "
                   "connect/wire node inputs: there is no AddNode / SetNodeInput, "
                   "so you cannot add node, create node, or connect nodes "
                   "programmatically.",
        "recommended": "Build complex topologies once in the GUI, save a "
                       "PowerGrade .drx, and apply with safe_apply_drx / "
                       "ApplyGradeFromDRX (full-replace, no append). Propagate an "
                       "existing graph with CopyGrades([targets]).",
        "tags": ["color", "node-graph", "missing-method", "drx"],
        "verified_on": "DaVinci Resolve Studio 20.2.1.6 (live graph_methods)",
    },
    {
        "symbol": "TimelineItem.ApplyGradeFromDRX",
        "object": "TimelineItem / Graph",
        "reality": "Replaces the ENTIRE node graph (no append mode). In direct "
                   "scripting it consistently returns None instead of a "
                   "success/failure flag, and when the scripting bridge has "
                   "degraded the method reference itself can become None "
                   "(hasattr True, getattr None).",
        "recommended": "Use timeline_item_color.safe_apply_drx, which snapshots "
                       "the grade version first and validates via GetLUT readback; "
                       "re-fetch the item before each call and never cache the "
                       "bound method.",
        "tags": ["color", "drx", "unreliable-return", "bridge"],
        "verified_on": "DaVinci Resolve Studio 20.2.1.6 (live: full-replace) / 20.x session (None return)",
    },
    {
        "symbol": "Graph.SetLUT",
        "object": "Graph (Color page node)",
        "reality": "Returns True immediately, but DCTL/LUT compilation is "
                   "ASYNCHRONOUS — a build-error dialog appears later. A True "
                   "return does not mean the LUT/DCTL compiled or applied.",
        "recommended": "Do not trust the return value. Let Resolve settle, then "
                       "verify via GetLUT readback and/or check the DCTL build "
                       "error dialog / ResolveDebug.txt.",
        "tags": ["color", "lut", "dctl", "unreliable-return", "async"],
        "verified_on": "DaVinci Resolve Studio 20.x (production color session)",
    },
    {
        "symbol": "Graph.GetLUT",
        "object": "Graph (Color page node)",
        "reality": "Only reliable for clips on the CURRENT timeline. After "
                   "switching timelines it can return empty/None even where LUTs "
                   "exist — never build reference-counting / cleanup logic on top "
                   "of cross-timeline GetLUT results.",
        "recommended": "Set each timeline current before scanning its clips, then "
                       "restore the original current timeline.",
        "tags": ["color", "lut", "timeline", "unreliable-return"],
        "verified_on": "DaVinci Resolve Studio 20.x (production color session)",
    },
    {
        "symbol": "Grade keyframes (per-clip dynamics)",
        "object": "TimelineItem / Graph",
        "reality": "No scripting API to create, read, or detect grade keyframes "
                   "(dynamics) inside a clip.",
        "recommended": "Split the clip at the change point and apply a different "
                       "CDL/grade per segment, or leave dynamic secondaries to a "
                       "human in the GUI.",
        "tags": ["color", "keyframe", "missing-method"],
        "verified_on": "DaVinci Resolve Studio 20.x (production color session)",
    },
    {
        "symbol": "Power Windows / qualifiers / tracking",
        "object": "TimelineItem",
        "reality": "No scripting API for Power Window shapes, HSL/luma "
                   "qualifiers, or tracking. The only secondary-region tools "
                   "exposed are the AI ones: CreateMagicMask / RegenerateMagicMask "
                   "(plus Stabilize / SmartReframe).",
        "recommended": "Bake window/qualifier structures into a .drx template, or "
                       "approximate soft-limiting in a custom DCTL.",
        "tags": ["color", "missing-method", "power-window", "qualifier"],
        "verified_on": "DaVinci Resolve Studio 20.2.1.6 (live item_methods)",
    },
    {
        "symbol": "Built-in scopes (waveform / histogram / vectorscope / parade)",
        "object": "(Color page UI)",
        "reality": "Resolve's built-in scopes have NO scripting API or data "
                   "export; they only render in the UI.",
        "recommended": "Pull a frame with GetCurrentClipThumbnailImage() "
                       "(in-memory, no disk I/O) and compute waveform/histogram/"
                       "vector locally in Python.",
        "tags": ["color", "scopes", "missing-method"],
        "verified_on": "DaVinci Resolve Studio 20.x (production session; confirmed vs official docs)",
    },
    {
        "symbol": "SetClipProperty('Input Color Space')",
        "object": "TimelineItem / MediaPoolItem (RCM)",
        "reality": "Accepts only exact RCM strings; anything slightly off fails "
                   "silently. Verified working values include 'DJI D-Gamut/D-Log', "
                   "'S-Gamut3.Cine/S-Log3' (no 'Sony' prefix), 'Rec.709 Gamma 2.4', "
                   "'ARRI LogC3'. Once set there is no API to reset a clip back to "
                   "the project/Auto default.",
        "recommended": "Keep an allowlist of verified strings and read back with "
                       "GetClipProperty after every set; record the chosen ICS "
                       "since it cannot be cleared.",
        "tags": ["color", "rcm", "enum", "silent-failure"],
        "verified_on": "DaVinci Resolve Studio 20.x (production color session)",
    },
    {
        "symbol": "Timeline.SetCurrentTimecode",
        "object": "Timeline",
        "reality": "Does not reliably move the playhead; it can freeze on the "
                   "previous frame, so a following ExportCurrentFrameAsStill / "
                   "still grab captures the WRONG (stale) frame. Worsens as the "
                   "scripting bridge degrades.",
        "recommended": "For frame-accurate output use the Deliver/render path, not "
                       "SetCurrentTimecode + still grab; re-read GetCurrentTimecode "
                       "to confirm before relying on the playhead.",
        "tags": ["timeline", "playhead", "unreliable-return", "bridge"],
        "verified_on": "DaVinci Resolve Studio 20.x (production color session)",
    },
    {
        "symbol": "Graph.ExportStills / Gallery still grab",
        "object": "Graph / GalleryStill",
        "reality": "Fails ('ensure the Gallery panel is open on the Color page') "
                   "when the Gallery panel is not actually visible.",
        "recommended": "Use ExportCurrentFrameAsStill (no Gallery panel needed), "
                       "or open the Color page Gallery panel before calling.",
        "tags": ["color", "gallery", "stills", "ui-state"],
        "verified_on": "DaVinci Resolve Studio 20.x (production color session)",
    },
    {
        "symbol": "fusionscript bridge (stateful, degrades under churn)",
        "object": "(scripting bridge runtime)",
        "reality": "The scripting bridge is a stateful service living inside the "
                   "Resolve process. After dozens of short-lived connections / "
                   "held-then-stale remote object references it DEGRADES: bound "
                   "methods become None, SaveProject raises NoneType, "
                   "SetCurrentTimecode freezes the playhead, GetClipProperty "
                   "returns empty. The symptoms masquerade as unrelated bugs.",
        "recommended": "Use one long-lived connection (the MCP server) and "
                       "re-fetch objects per call instead of bulk one-off scripts. "
                       "When symptoms appear, restart Resolve to reset the bridge "
                       "(SaveProject first where possible).",
        "tags": ["runtime", "bridge", "stability", "silent-failure"],
        "verified_on": "DaVinci Resolve Studio 20.x (production color session)",
    },
    {
        "symbol": "Timeline.GetItemListInTrack",
        "object": "Timeline",
        "reality": "Returns ALL items on the track including transitions, and is "
                   "blind to multi-track occlusion (clips hidden under higher "
                   "tracks still appear). Naive cleanup over its output can delete "
                   "transitions/visible clips.",
        "recommended": "Filter out transition items and compute visibility "
                       "top-track-down before acting; treat only genuinely "
                       "uncovered clips as visible.",
        "tags": ["timeline", "occlusion", "transition"],
        "verified_on": "DaVinci Resolve Studio 20.x (production color session)",
    },
    {
        "symbol": "Folder.SetName",
        "object": "MediaPool Folder",
        "reality": "Does not exist — a media-pool bin (Folder) cannot be renamed "
                   "from scripting (mirrors Timeline.GetTimelineByName being "
                   "absent).",
        "recommended": "Name the bin at creation, or rename via the GUI / at the "
                       ".drt XML layer; use SetCurrentFolder to navigate.",
        "tags": ["media-pool", "missing-method", "folder"],
        "verified_on": "DaVinci Resolve Studio 20.x (production session)",
    },
    {
        "symbol": "MediaPoolItem variable speed / FCPXML timeMap import",
        "object": "MediaPoolItem / MediaPool.ImportTimelineFromFile",
        "reality": "There is no API to set a clip's variable (ramped) speed, and "
                   "importing FCPXML whose clips carry <timeMap> makes Resolve "
                   "auto-wrap each into a compound clip — unavoidable via API or "
                   "import flags.",
        "recommended": "To flatten while keeping speed ramps, edit the .drt XML "
                       "directly (preserve the MediaTimemapBA blob) instead of an "
                       "FCPXML round-trip — see docs/notes/drt-format-notes.md.",
        "tags": ["media-pool", "speed", "fcpxml", "compound", "missing-method"],
        "verified_on": "DaVinci Resolve Studio 20.x (production session)",
    },
    {
        "symbol": "MediaPool.RelinkClips",
        "object": "MediaPool",
        "reality": "Returns only a single batch bool; it does not report which "
                   "clips relinked vs stayed offline.",
        "recommended": "After calling, read GetClipProperty('Offline') on each "
                       "affected clip to learn the real per-clip outcome.",
        "tags": ["media-pool", "relink", "unreliable-return"],
        "verified_on": "DaVinci Resolve Studio 20.x (production session)",
    },
]


def lookup_api_truth(query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return verified facts matching `query`, or all facts if no query.

    Matches a case-insensitive substring against the symbol, tags, and reality.
    """
    if not query:
        return list(API_TRUTH)
    q = query.lower()
    out = []
    for e in API_TRUTH:
        hay = " ".join([
            e.get("symbol", ""),
            e.get("object", ""),
            e.get("reality", ""),
            " ".join(e.get("tags", [])),
        ]).lower()
        if q in hay:
            out.append(e)
    return out
