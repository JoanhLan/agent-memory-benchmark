<template>
  <div class="app-shell">
    <header class="header">
      <div class="logo">
        <div class="logo-icon">BM</div>
        <div>
          <h1>Benchmark Lab</h1>
          <div class="sub">Legacy TiMEM / MemOS / Mem0 lab. AML text track: python main.py aml</div>
        </div>
      </div>
      <div class="health-row">
        <span :class="['health-pill', health.timem?.ok ? 'ok' : 'bad']">TiMEM</span>
        <span :class="['health-pill', health.memos?.ok ? 'ok' : 'bad']">MemOS</span>
        <span :class="['health-pill', health.mem0?.ok ? 'ok' : 'bad']">Mem0</span>
        <span :class="['health-pill', health.judge?.ok ? 'ok' : 'bad']">Judge</span>
        <button class="btn btn-sm" type="button" @click="refreshHealth">检测</button>
      </div>
    </header>

    <div class="body-row">
      <aside class="sidebar">
        <div class="sidebar-title">导航</div>
        <button
          v-for="item in nav"
          :key="item.id"
          type="button"
          :class="['nav-btn', section === item.id ? 'active' : '']"
          @click="goSection(item.id)"
        >
          {{ item.label }}
        </button>
        <div class="sidebar-spacer" />
        <div class="run-picker">
          <label class="form-label">Run 列表</label>
          <div class="run-list">
            <p v-if="!runs.length" class="run-list-empty muted">暂无记录</p>
            <div
              v-for="r in runs"
              :key="r.run_id"
              :class="['run-row', runId === r.run_id ? 'active' : '']"
            >
              <button type="button" class="run-select-btn" @click="selectRun(r.run_id)">
                <span class="run-id-text">{{ r.run_id }}</span>
                <span v-if="r.job?.status === 'running'" class="run-badge">运行中</span>
              </button>
              <button
                type="button"
                class="run-delete-btn"
                title="删除此 Run"
                :disabled="r.job?.status === 'running' || deletingRunId === r.run_id"
                @click.stop="deleteRunItem(r.run_id)"
              >
                ×
              </button>
            </div>
          </div>
          <label class="form-label" style="margin-top: 10px">Run ID（可选）</label>
          <input
            v-model="newRunIdInput"
            class="form-input"
            type="text"
            placeholder="留空自动生成；自定义仅字母数字_-，如 20260811_en_smoke"
            :disabled="creatingRun"
            @keydown.enter.prevent="newRun"
          />
          <button
            class="btn btn-sm btn-primary"
            type="button"
            style="margin-top: 8px; width: 100%"
            :disabled="creatingRun"
            @click="newRun"
          >
            {{ creatingRun ? "创建中…" : "新建 Run" }}
          </button>
          <p v-if="sidebarError" class="sidebar-error">{{ sidebarError }}</p>
        </div>
      </aside>

      <main class="main">
        <ExperimentPanel
          v-if="section === 'experiment'"
          :run-id="runId"
          @run-created="onRunCreated"
          @job-started="pollRuns"
        />
        <DatasetPanel v-else-if="section === 'dataset'" :run-id="runId" />
        <IngestPanel v-else-if="section === 'ingest'" :run-id="runId" />
        <RetrievalPanel v-else-if="section === 'retrieval'" :run-id="runId" @job-started="pollRuns" />
        <ComparePanel v-else-if="section === 'compare'" :run-id="runId" />
        <TimemSweepPanel v-else-if="section === 'sweep'" :run-id="runId" />
        <DebugPanel v-else-if="section === 'debug'" :run-id="runId" />
        <SettingsPanel v-else-if="section === 'settings'" />
      </main>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, provide, ref, watch } from "vue";
import { createRun, deleteRun, fetchHealth, fetchJob, fetchMeta, fetchRuns } from "./api";
import ComparePanel from "./views/panels/ComparePanel.vue";
import TimemSweepPanel from "./views/panels/TimemSweepPanel.vue";
import DebugPanel from "./views/panels/DebugPanel.vue";
import DatasetPanel from "./views/panels/DatasetPanel.vue";
import ExperimentPanel from "./views/panels/ExperimentPanel.vue";
import IngestPanel from "./views/panels/IngestPanel.vue";
import RetrievalPanel from "./views/panels/RetrievalPanel.vue";
import SettingsPanel from "./views/panels/SettingsPanel.vue";

const nav = [
  { id: "experiment", label: "实验 Run" },
  { id: "dataset", label: "写入语料" },
  { id: "ingest", label: "写入 Ingest" },
  { id: "retrieval", label: "检索 Retrieval" },
  { id: "compare", label: "对比 Compare" },
  { id: "sweep", label: "Sweep TiMEM" },
  { id: "debug", label: "调试 Debug" },
  { id: "settings", label: "设置 Settings" },
];

const section = ref("experiment");
const runId = ref("");
const runs = ref([]);
const health = ref({ timem: {}, memos: {}, mem0: {}, judge: {} });
const creatingRun = ref(false);
const newRunIdInput = ref("");
const deletingRunId = ref("");
const sidebarError = ref("");

const refreshTick = ref(0);

function bumpRefresh() {
  refreshTick.value += 1;
  pollRuns();
}

provide("selectedRunId", runId);
provide("refreshRuns", pollRuns);
provide("refreshTick", refreshTick);
provide("bumpRefresh", bumpRefresh);

function syncUrl() {
  const u = new URL(window.location.href);
  u.searchParams.set("section", section.value);
  if (runId.value) u.searchParams.set("run", runId.value);
  else u.searchParams.delete("run");
  window.history.replaceState({}, "", u);
}

function goSection(id) {
  section.value = id;
  syncUrl();
}

async function pollRuns() {
  try {
    runs.value = await fetchRuns();
  } catch {
    /* ignore */
  }
}

async function refreshHealth() {
  try {
    health.value = await fetchHealth();
  } catch {
    health.value = { timem: { ok: false }, memos: { ok: false }, mem0: { ok: false }, judge: { ok: false } };
  }
}

async function newRun() {
  sidebarError.value = "";
  creatingRun.value = true;
  try {
    const custom = newRunIdInput.value.trim();
    const { run_id } = await createRun(custom || undefined);
    runId.value = run_id;
    newRunIdInput.value = "";
    await pollRuns();
    goSection("experiment");
  } catch (e) {
    const msg = e.message || "创建失败";
    const isFormat =
      msg.includes("run_id must") ||
      msg.includes("run_id cannot") ||
      msg.includes("reserved") ||
      msg.includes("path separators");
    sidebarError.value = isFormat
      ? msg
      : msg +
        " — 若接口异常：Ctrl+C 后执行 python main.py dashboard（确认 8765 无旧进程）";
  } finally {
    creatingRun.value = false;
  }
}

function onRunCreated(id) {
  runId.value = id;
  pollRuns();
}

function selectRun(id) {
  runId.value = id;
  syncUrl();
}

async function deleteRunItem(id) {
  if (!id) return;
  const row = runs.value.find((r) => r.run_id === id);
  const running = row?.job?.status === "running";
  if (running) {
    sidebarError.value = "任务运行中，请等待完成；若已卡住请重启 dashboard 后再删";
    return;
  }
  if (!window.confirm(`确定删除 Run ${id}？\n将删除 reports/${id}/ 下全部报告，且不可恢复。`)) {
    return;
  }
  sidebarError.value = "";
  deletingRunId.value = id;
  try {
    await deleteRun(id);
    if (runId.value === id) runId.value = "";
    await pollRuns();
    syncUrl();
  } catch (e) {
    const msg = e.message || "删除失败";
    sidebarError.value =
      msg +
      (msg.includes("501") || msg.includes("405")
        ? " — 请 Ctrl+C 后重新运行 python main.py dashboard（当前是旧服务）"
        : "");
  } finally {
    deletingRunId.value = "";
  }
}

let runsTimer;
let jobTimer;
let lastJobStatus = "";

async function pollActiveJob() {
  if (!runId.value) return;
  try {
    const job = await fetchJob(runId.value);
    const status = job?.status || "idle";
    if (lastJobStatus === "running" && (status === "completed" || status === "failed")) {
      bumpRefresh();
    }
    lastJobStatus = status;
  } catch {
    /* ignore */
  }
}

watch(runId, () => {
  lastJobStatus = "";
  if (jobTimer) clearInterval(jobTimer);
  if (runId.value) jobTimer = setInterval(pollActiveJob, 3000);
});

onMounted(async () => {
  const q = new URLSearchParams(window.location.search);
  if (q.get("section")) section.value = q.get("section");
  if (q.get("run")) runId.value = q.get("run");
  await Promise.all([pollRuns(), refreshHealth()]);
  try {
    await fetchMeta();
  } catch {
    sidebarError.value = "API 版本过旧，删除/新建可能失败。请 Ctrl+C 后执行: python main.py dashboard";
  }
  runsTimer = setInterval(pollRuns, 5000);
  if (runId.value) jobTimer = setInterval(pollActiveJob, 3000);
});

onUnmounted(() => {
  if (runsTimer) clearInterval(runsTimer);
  if (jobTimer) clearInterval(jobTimer);
});
</script>
