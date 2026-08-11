<template>
  <div class="form-grid">
    <div class="form-group">
      <label class="form-label">数据集</label>
      <select v-model="opts.dataset.value" class="form-input">
        <option value="fixture">Fixture（默认，快速）</option>
        <option value="locomo">LoCoMo（10 persona）</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">评测预设</label>
      <select v-model="opts.preset.value" class="form-input">
        <option value="stable">stable（top_k=10, enhanced_semantic）</option>
        <option value="paper">paper（top_k=20, 论文对齐）</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">系统</label>
      <div class="check-row">
        <label><input type="checkbox" v-model="opts.systemsTimem.value" /> TiMEM</label>
        <label><input type="checkbox" v-model="opts.systemsMemos.value" /> MemOS</label>
        <label><input type="checkbox" v-model="opts.systemsMem0.value" /> Mem0</label>
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">选项</label>
      <div class="check-row">
        <label><input type="checkbox" v-model="opts.runJudge.value" /> ARK Judge</label>
        <label v-if="showSkipT1"><input type="checkbox" v-model="opts.skipT1.value" /> Full 跳过 T1</label>
      </div>
    </div>
    <div class="form-group" style="grid-column: 1 / -1">
      <details class="timem-advanced">
        <summary class="form-label">检索并发（留空使用 config/default.yaml）</summary>
        <div class="form-grid" style="margin-top: 8px">
          <div class="form-group">
            <label class="form-label">query_concurrency (memos/mem0)</label>
            <input
              v-model="opts.queryConcurrency.value"
              type="number"
              min="1"
              class="form-input"
              placeholder="10"
            />
          </div>
          <div class="form-group">
            <label class="form-label">timem_query_concurrency</label>
            <input
              v-model="opts.timemQueryConcurrency.value"
              type="number"
              min="1"
              class="form-input"
              placeholder="3"
            />
          </div>
          <div class="form-group">
            <label class="form-label">judge_concurrency</label>
            <input
              v-model="opts.judgeConcurrency.value"
              type="number"
              min="1"
              class="form-input"
              placeholder="10"
            />
          </div>
          <div class="form-group">
            <label class="form-label">backfill_concurrency (T1 / L2)</label>
            <input
              v-model="opts.backfillConcurrency.value"
              type="number"
              min="1"
              class="form-input"
              placeholder="3"
            />
          </div>
          <div class="form-group">
            <label class="form-label">选项</label>
            <div class="check-row">
              <label><input type="checkbox" v-model="opts.pipelineMode.value" /> Search→Judge 流水线</label>
            </div>
          </div>
        </div>
      </details>
    </div>
    <div v-if="opts.systemsTimem.value" class="form-group" style="grid-column: 1 / -1">
      <label class="form-label">TiMEM Ingest</label>
      <div class="check-row" style="align-items: center; gap: 16px; flex-wrap: wrap">
        <label>
          记忆语言
          <select v-model="opts.memoryLanguage.value" style="margin-left: 8px">
            <option value="en">English (en)</option>
            <option value="zh">中文 (zh)</option>
          </select>
        </label>
        <label>
          <input type="checkbox" v-model="opts.waitTimemL2OnIngest.value" />
          Ingest 后等待 TiMEM L2
        </label>
      </div>
      <p class="hint" style="margin-top: 6px">
        记忆语言会在 Ingest 前写入 TiMEM Policy（expert=benchmark）。英文 LoCoMo 建议选 en。
        未勾选 L2 时 Ingest 仅写入记忆；可稍后用手动 Backfill 或 T0 检索补 L2。
      </p>
    </div>
    <div class="form-group" style="grid-column: 1 / -1">
      <label class="form-label">TiMEM Backfill 层级（Pipeline / 仅 Backfill）</label>
      <div class="check-row">
        <label v-for="layer in opts.backfillLayerIds" :key="layer">
          <input
            type="checkbox"
            :checked="opts.isBackfillLayerSelected(layer)"
            @change="opts.toggleBackfillLayer(layer)"
          />
          {{ layer }}
        </label>
      </div>
      <p v-if="!opts.hasBackfillLayers.value" class="hint" style="margin-top: 6px">
        Pipeline 未选层级时将跳过 Backfill；「仅 TiMEM Backfill」需至少选一层
      </p>
    </div>
    <div v-if="showTimemAdvanced && opts.systemsTimem.value" class="form-group" style="grid-column: 1 / -1">
      <details class="timem-advanced">
        <summary class="form-label">TiMEM 高级检索参数（覆盖预设）</summary>
        <div class="form-grid" style="margin-top: 8px">
          <div class="form-group">
            <label class="form-label">search_mode</label>
            <select v-model="opts.timemSearchMode.value" class="form-input">
              <option value="">（使用预设）</option>
              <option value="semantic">semantic</option>
              <option value="enhanced_semantic">enhanced_semantic</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">use_hybrid</label>
            <select v-model="opts.timemUseHybrid.value" class="form-input">
              <option value="">（使用预设）</option>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">enable_memories_rethink</label>
            <select v-model="opts.timemRethink.value" class="form-input">
              <option value="">（使用预设）</option>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          </div>
        </div>
      </details>
    </div>
  </div>
</template>

<script setup>
defineProps({
  opts: { type: Object, required: true },
  showSkipT1: { type: Boolean, default: true },
  showTimemAdvanced: { type: Boolean, default: false },
});
</script>
