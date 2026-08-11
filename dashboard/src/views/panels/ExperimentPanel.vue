<template>
  <div>
    <div class="section-header">
      <h2 class="section-title">实验 / Run</h2>
      <p class="muted">Pipeline（Ingest → Backfill → T0）· Full（Ingest → T0 → T1）· 或分步执行</p>
    </div>

    <div v-if="!runId" class="card card-pad empty-hint">
      请先在左侧选择 Run，或点击「新建 Run」。
    </div>

    <div v-else class="card card-pad">
      <div class="form-group" style="margin-bottom: 12px">
        <label class="form-label">Run ID</label>
        <input class="form-input" :value="runId" readonly />
      </div>

      <RunOptionsForm :opts="opts" :show-timem-advanced="true" />

      <div class="btn-row">
        <button class="btn btn-primary" type="button" :disabled="busy" @click="start('pipeline')">
          一键 Pipeline（Ingest → Backfill → T0）
        </button>
        <button class="btn" type="button" :disabled="busy" @click="start('full')">
          一键 Full
        </button>
        <button class="btn" type="button" :disabled="busy" @click="start('ingest')">仅 Ingest</button>
        <button class="btn" type="button" :disabled="busy" @click="start('retrieve', 'T0')">仅 T0</button>
        <button class="btn" type="button" :disabled="busy" @click="start('retrieve', 'T1')">仅 T1</button>
        <button
          class="btn"
          type="button"
          :disabled="busy || !opts.hasBackfillLayers.value"
          @click="start('backfill')"
        >
          仅 TiMEM Backfill
        </button>
      </div>

      <p class="hint">
        推荐 <strong>一键 Pipeline</strong>：先 Ingest，再按上方勾选层级 Backfill（可不选，T0 仍有 L2 安全网），最后 T0 检索。
        <strong>一键 Full</strong> 为 Ingest → T0 → T1（T1 用 config 默认 L2–L5）。若只点「仅 T0」而未 Ingest，对比页会全是 0。
      </p>

      <div v-if="job" class="job-status">
        <div class="job-meta">
          <span :class="['badge', statusBadge]">{{ job.status }} · {{ job.step }}</span>
          <span class="muted">{{ job.percent ?? 0 }}%</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: (job.percent || 0) + '%' }" />
        </div>
        <div v-if="job.error" class="error-box">{{ job.error }}</div>
        <pre class="log-box">{{ logText }}</pre>
      </div>
      <div v-if="message" class="error-box" style="margin-top: 12px">{{ message }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onUnmounted, ref, watch } from "vue";
import RunOptionsForm from "../../components/RunOptionsForm.vue";
import { useBenchmarkOptions } from "../../composables/useBenchmarkOptions";
import { fetchJob, startJob } from "../../api";

const props = defineProps({ runId: { type: String, default: "" } });
const emit = defineEmits(["job-started"]);
const bumpRefresh = inject("bumpRefresh", () => {});

const opts = useBenchmarkOptions();
const job = ref(null);
const message = ref("");
const busy = ref(false);
let pollTimer;

const statusBadge = computed(() => {
  const s = job.value?.status;
  if (s === "completed") return "badge-ok";
  if (s === "failed") return "badge-bad";
  if (s === "running") return "badge-warn";
  return "";
});

const logText = computed(() => (job.value?.logs || []).join("\n") || "（暂无日志）");

async function start(type, mode = "T0") {
  message.value = "";
  if (type === "backfill") {
    if (!opts.hasBackfillLayers.value) {
      message.value = "请至少选择一个 Backfill 层级";
      return;
    }
  } else if (!opts.systemsList().length) {
    message.value = "请至少选择一个系统";
    return;
  }
  busy.value = true;
  try {
    job.value = await startJob(props.runId, opts.jobPayload({ type, mode }));
    emit("job-started");
    startPolling();
  } catch (e) {
    message.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function pollJob() {
  if (!props.runId) return;
  try {
    const prev = job.value?.status;
    job.value = await fetchJob(props.runId);
    // Do not applyFromJob here — it overwrites the form every 2s with the last
    // job's options (e.g. rethink=true), so UI changes snap back.
    busy.value = job.value?.status === "running";
    if (prev === "running" && job.value?.status === "completed") bumpRefresh();
  } catch {
    /* ignore */
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollJob, 2000);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

watch(
  () => props.runId,
  () => {
    job.value = null;
    if (props.runId) {
      pollJob().then(() => {
        if (job.value) opts.applyFromJob(job.value);
      });
      startPolling();
    } else stopPolling();
  },
  { immediate: true }
);

onUnmounted(stopPolling);
</script>
