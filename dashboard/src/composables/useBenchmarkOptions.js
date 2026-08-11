import { computed, ref, watch } from "vue";
import { SYSTEM_IDS } from "../constants/systems";

const STORAGE_KEY = "benchmark_lab_options";
const BACKFILL_LAYER_IDS = ["L2", "L3", "L4", "L5"];

function loadStored() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveStored(data) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

/** Shared dataset / systems / judge options (persisted in localStorage). */
export function useBenchmarkOptions() {
  const stored = loadStored();
  const dataset = ref(stored.dataset || "fixture");
  const preset = ref(stored.preset || "stable");
  const systemsTimem = ref(stored.systemsTimem !== false);
  const systemsMemos = ref(stored.systemsMemos !== false);
  const systemsMem0 = ref(stored.systemsMem0 !== false);
  const runJudge = ref(stored.runJudge !== false);
  const skipT1 = ref(!!stored.skipT1);
  const timemSearchMode = ref(stored.timemSearchMode || "");
  const timemUseHybrid = ref(stored.timemUseHybrid || "");
  const timemRethink = ref(stored.timemRethink || "");
  const queryConcurrency = ref(stored.queryConcurrency ?? "");
  const timemQueryConcurrency = ref(stored.timemQueryConcurrency ?? "");
  const judgeConcurrency = ref(stored.judgeConcurrency ?? "");
  const backfillConcurrency = ref(stored.backfillConcurrency ?? "");
  const pipelineMode = ref(stored.pipelineMode !== false);
  const backfillLayers = ref(
    Array.isArray(stored.backfillLayers) && stored.backfillLayers.length
      ? stored.backfillLayers.filter((l) => BACKFILL_LAYER_IDS.includes(l))
      : ["L2"]
  );
  const waitTimemL2OnIngest = ref(!!stored.waitTimemL2OnIngest);
  const memoryLanguage = ref(stored.memoryLanguage === "zh" ? "zh" : "en");

  watch(
    [
      dataset,
      preset,
      systemsTimem,
      systemsMemos,
      systemsMem0,
      runJudge,
      skipT1,
      timemSearchMode,
      timemUseHybrid,
      timemRethink,
      queryConcurrency,
      timemQueryConcurrency,
      judgeConcurrency,
      backfillConcurrency,
      pipelineMode,
      backfillLayers,
      waitTimemL2OnIngest,
      memoryLanguage,
    ],
    () => {
      saveStored({
        dataset: dataset.value,
        preset: preset.value,
        systemsTimem: systemsTimem.value,
        systemsMemos: systemsMemos.value,
        systemsMem0: systemsMem0.value,
        runJudge: runJudge.value,
        skipT1: skipT1.value,
        timemSearchMode: timemSearchMode.value,
        timemUseHybrid: timemUseHybrid.value,
        timemRethink: timemRethink.value,
        queryConcurrency: queryConcurrency.value,
        timemQueryConcurrency: timemQueryConcurrency.value,
        judgeConcurrency: judgeConcurrency.value,
        backfillConcurrency: backfillConcurrency.value,
        pipelineMode: pipelineMode.value,
        backfillLayers: backfillLayers.value,
        waitTimemL2OnIngest: waitTimemL2OnIngest.value,
        memoryLanguage: memoryLanguage.value,
      });
    }
  );

  const useFixture = computed(() => dataset.value === "fixture");
  const personaCount = computed(() => (useFixture.value ? 1 : 10));
  const hasBackfillLayers = computed(() => backfillLayers.value.length > 0);

  function systemsList() {
    const s = [];
    if (systemsTimem.value) s.push("timem");
    if (systemsMemos.value) s.push("memos");
    if (systemsMem0.value) s.push("mem0");
    return s;
  }

  function timemOverridesPayload() {
    const out = {};
    if (timemSearchMode.value) out.search_mode = timemSearchMode.value;
    if (timemUseHybrid.value === "true") out.use_hybrid = true;
    if (timemUseHybrid.value === "false") out.use_hybrid = false;
    if (timemRethink.value === "true") out.enable_memories_rethink = true;
    if (timemRethink.value === "false") out.enable_memories_rethink = false;
    return out;
  }

  function applyFromJob(job) {
    const opts = job?.options;
    if (!opts) return;
    if (opts.use_fixture != null) dataset.value = opts.use_fixture ? "fixture" : "locomo";
    if (opts.preset) preset.value = opts.preset;
    if (Array.isArray(opts.systems)) {
      systemsTimem.value = opts.systems.includes("timem");
      systemsMemos.value = opts.systems.includes("memos");
      systemsMem0.value = opts.systems.includes("mem0");
    }
    if (opts.run_judge != null) runJudge.value = !!opts.run_judge;
    if (opts.skip_t1 != null) skipT1.value = !!opts.skip_t1;
    const tovr = opts.timem_overrides || {};
    timemSearchMode.value = tovr.search_mode || "";
    if (tovr.use_hybrid === true) timemUseHybrid.value = "true";
    else if (tovr.use_hybrid === false) timemUseHybrid.value = "false";
    if (tovr.enable_memories_rethink === true) timemRethink.value = "true";
    else if (tovr.enable_memories_rethink === false) timemRethink.value = "false";
    const rovr = opts.retrieval_overrides || {};
    if (rovr.query_concurrency != null) queryConcurrency.value = String(rovr.query_concurrency);
    if (rovr.timem_query_concurrency != null) timemQueryConcurrency.value = String(rovr.timem_query_concurrency);
    if (rovr.judge_concurrency != null) judgeConcurrency.value = String(rovr.judge_concurrency);
    if (rovr.backfill_concurrency != null) backfillConcurrency.value = String(rovr.backfill_concurrency);
    if (rovr.pipeline_mode != null) pipelineMode.value = !!rovr.pipeline_mode;
    if (Array.isArray(opts.backfill_layers) && opts.backfill_layers.length) {
      backfillLayers.value = opts.backfill_layers.filter((l) => BACKFILL_LAYER_IDS.includes(l));
    }
    if (opts.wait_timem_l2_on_ingest != null) {
      waitTimemL2OnIngest.value = !!opts.wait_timem_l2_on_ingest;
    }
    if (opts.memory_language === "zh" || opts.memory_language === "en") {
      memoryLanguage.value = opts.memory_language;
    }
  }

  function isBackfillLayerSelected(layer) {
    return backfillLayers.value.includes(layer);
  }

  function toggleBackfillLayer(layer) {
    const set = new Set(backfillLayers.value);
    if (set.has(layer)) set.delete(layer);
    else set.add(layer);
    backfillLayers.value = BACKFILL_LAYER_IDS.filter((l) => set.has(l));
  }

  function backfillLayersPayload() {
    return [...backfillLayers.value];
  }

  function retrievalOverridesPayload() {
    const out = {};
    const q = parseInt(queryConcurrency.value, 10);
    const tq = parseInt(timemQueryConcurrency.value, 10);
    const j = parseInt(judgeConcurrency.value, 10);
    const b = parseInt(backfillConcurrency.value, 10);
    if (!Number.isNaN(q) && q > 0) out.query_concurrency = q;
    if (!Number.isNaN(tq) && tq > 0) out.timem_query_concurrency = tq;
    if (!Number.isNaN(j) && j > 0) out.judge_concurrency = j;
    if (!Number.isNaN(b) && b > 0) out.backfill_concurrency = b;
    if (!pipelineMode.value) out.pipeline_mode = false;
    return out;
  }

  function jobPayload(extra = {}) {
    const timem_overrides = timemOverridesPayload();
    const retrieval_overrides = retrievalOverridesPayload();
    const payload = {
      use_fixture: useFixture.value,
      persona_count: personaCount.value,
      systems: systemsList(),
      run_judge: runJudge.value,
      skip_t1: skipT1.value,
      preset: preset.value,
      timem_overrides: Object.keys(timem_overrides).length ? timem_overrides : undefined,
      retrieval_overrides: Object.keys(retrieval_overrides).length ? retrieval_overrides : undefined,
      wait_timem_l2_on_ingest: waitTimemL2OnIngest.value,
      memory_language: memoryLanguage.value,
      ...extra,
    };
    if (extra.type === "backfill") {
      payload.systems = ["timem"];
      payload.backfill_layers = backfillLayersPayload();
    }
    if (extra.type === "pipeline") {
      payload.backfill_layers = backfillLayersPayload();
      payload.wait_timem_l2_on_ingest = false;
    }
    return payload;
  }

  return {
    dataset,
    preset,
    systemsTimem,
    systemsMemos,
    systemsMem0,
    runJudge,
    skipT1,
    timemSearchMode,
    timemUseHybrid,
    timemRethink,
    queryConcurrency,
    timemQueryConcurrency,
    judgeConcurrency,
    backfillConcurrency,
    pipelineMode,
    backfillLayers,
    waitTimemL2OnIngest,
    memoryLanguage,
    hasBackfillLayers,
    useFixture,
    personaCount,
    systemsList,
    timemOverridesPayload,
    retrievalOverridesPayload,
    isBackfillLayerSelected,
    toggleBackfillLayer,
    backfillLayersPayload,
    applyFromJob,
    jobPayload,
    allSystemIds: SYSTEM_IDS,
    backfillLayerIds: BACKFILL_LAYER_IDS,
  };
}
