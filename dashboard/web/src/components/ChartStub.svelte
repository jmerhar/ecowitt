<script lang="ts">
  /** Stands in for Chart in tests, which jsdom cannot draw: lists the lines it was given. */
  import type { ChartData } from "../lib/chart";
  let { data }: { data: ChartData } = $props();
</script>

<ul data-testid="chart">
  {#each data.lines as line (line.label)}<li>{line.label}</li>{/each}
</ul>
