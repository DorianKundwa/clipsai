<script lang="ts">
import { videoStore } from '#lib/stores/videoStore.svelte';
import { formatTime } from '#lib/video';

let host = $state<HTMLDivElement | null>(null);
let canvas = $state<HTMLCanvasElement | null>(null);

let width = $state(720);
const height = 92;
const HANDLE_HIT = 10;

let dragging = $state<'scrub' | 'in' | 'out' | null>(null);
let hoverTime = $state<number | null>(null);

const duration = $derived(Math.max(videoStore.duration, 0.001));

$effect(() => {
	const element = host;
	if (!element) return;

	const observer = new ResizeObserver((entries) => {
		const next = entries[0]?.contentRect.width ?? 0;
		if (next > 0) width = next;
	});
	observer.observe(element);
	return () => observer.disconnect();
});

/** Ruler ticks with a step that keeps labels ~90px apart. */
function tickStep(seconds: number): number {
	const candidates = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
	const target = seconds / 8;
	return candidates.find((step) => step >= target) ?? 900;
}

function toX(time: number, total: number): number {
	return (Math.min(Math.max(time / total, 0), 1) * width);
}

function toTime(clientX: number): number {
	const rect = canvas?.getBoundingClientRect();
	if (!rect || rect.width === 0) return 0;
	return Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1) * duration;
}

$effect(() => {
	// Tracked reads: everything that affects the drawing.
	const element = canvas;
	const w = width;
	const total = duration;
	const inPoint = videoStore.inPoint;
	const outPoint = videoStore.outPoint;
	const playhead = videoStore.currentTime;
	const hover = hoverTime;
	const active = dragging;

	if (!element || w <= 0) return;

	const dpr = Math.min(window.devicePixelRatio || 1, 2);
	const pixelWidth = Math.round(w * dpr);
	const pixelHeight = Math.round(height * dpr);
	if (element.width !== pixelWidth) element.width = pixelWidth;
	if (element.height !== pixelHeight) element.height = pixelHeight;

	const context = element.getContext('2d');
	if (!context) return;

	context.setTransform(dpr, 0, 0, dpr, 0, 0);
	context.clearRect(0, 0, w, height);

	const trackTop = 22;
	const trackBottom = height - 22;
	const xIn = toX(inPoint, total);
	const xOut = toX(outPoint, total);

	// track
	context.fillStyle = 'rgba(255,255,255,0.035)';
	context.beginPath();
	context.roundRect(0, trackTop, w, trackBottom - trackTop, 6);
	context.fill();

	// selected range
	context.fillStyle = 'rgba(215,255,62,0.10)';
	context.fillRect(xIn, trackTop, Math.max(xOut - xIn, 0), trackBottom - trackTop);

	// ruler + labels
	const step = tickStep(total);
	context.font = '10px ui-monospace, monospace';
	context.textBaseline = 'top';
	for (let time = 0; time <= total + 0.0001; time += step) {
		const x = toX(time, total);
		const major = Math.abs(time % (step * 2)) < 0.001;
		context.strokeStyle = major ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.1)';
		context.beginPath();
		context.moveTo(x + 0.5, trackTop);
		context.lineTo(x + 0.5, trackTop + (major ? 7 : 4));
		context.stroke();

		if (major) {
			context.fillStyle = 'rgba(139,149,164,0.9)';
			context.fillText(formatTime(time), Math.min(x + 4, w - 46), 3);
		}
	}

	// hover readout
	if (hover !== null && active === null) {
		const x = toX(hover, total);
		context.strokeStyle = 'rgba(255,255,255,0.25)';
		context.beginPath();
		context.moveTo(x, trackTop);
		context.lineTo(x, trackBottom);
		context.stroke();
		context.fillStyle = 'rgba(233,236,241,0.9)';
		context.font = '10px ui-monospace, monospace';
		const label = formatTime(hover);
		const labelWidth = context.measureText(label).width;
		context.fillText(label, Math.min(Math.max(x - labelWidth / 2, 2), w - labelWidth - 2), trackBottom + 6);
	}

	// trim handles
	const drawHandle = (x: number, hot: boolean) => {
		context.fillStyle = hot ? '#ffffff' : '#d7ff3e';
		context.beginPath();
		context.roundRect(x - 2, trackTop - 4, 4, trackBottom - trackTop + 8, 2);
		context.fill();
		context.fillStyle = 'rgba(10,11,13,0.85)';
		context.fillRect(x - 0.75, trackTop + 6, 1.5, 8);
		context.fillRect(x - 0.75, trackBottom - 14, 1.5, 8);
	};
	drawHandle(xIn, active === 'in');
	drawHandle(xOut, active === 'out');

	// playhead
	const xPlay = toX(playhead, total);
	context.strokeStyle = 'rgba(255,255,255,0.85)';
	context.lineWidth = 1.5;
	context.beginPath();
	context.moveTo(xPlay, trackTop - 6);
	context.lineTo(xPlay, trackBottom + 2);
	context.stroke();
	context.fillStyle = '#ffffff';
	context.beginPath();
	context.moveTo(xPlay - 4, trackTop - 10);
	context.lineTo(xPlay + 4, trackTop - 10);
	context.lineTo(xPlay, trackTop - 3);
	context.closePath();
	context.fill();
	context.lineWidth = 1;
});

function onPointerDown(event: PointerEvent): void {
	if (!canvas) return;
	const time = toTime(event.clientX);
	const tolerance = (HANDLE_HIT / Math.max(width, 1)) * duration;

	if (Math.abs(time - videoStore.inPoint) <= tolerance) dragging = 'in';
	else if (Math.abs(time - videoStore.outPoint) <= tolerance) dragging = 'out';
	else {
		dragging = 'scrub';
		videoStore.seek(time);
	}

	canvas.setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent): void {
	const time = toTime(event.clientX);
	hoverTime = time;

	if (!dragging) return;
	if (dragging === 'in') videoStore.setIn(time);
	else if (dragging === 'out') videoStore.setOut(time);
	else videoStore.seek(time);
}

function onPointerUp(event: PointerEvent): void {
	if (canvas?.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
	dragging = null;
}

function onPointerLeave(): void {
	if (!dragging) hoverTime = null;
}
</script>

<div class="timeline" bind:this={host}>
	<canvas
		bind:this={canvas}
		style="height: {height}px"
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		onpointercancel={onPointerUp}
		onpointerleave={onPointerLeave}
		role="slider"
		aria-label="Timeline trim range"
		aria-valuemin={0}
		aria-valuemax={Math.round(duration * 100) / 100}
		aria-valuenow={Math.round(videoStore.currentTime * 100) / 100}
		tabindex="0"
	></canvas>

	<div class="legend">
		<span class="mono">in {formatTime(videoStore.inPoint)}</span>
		<span class="mono muted">len {(videoStore.trimLength).toFixed(2)}s</span>
		<span class="mono">out {formatTime(videoStore.outPoint)}</span>
	</div>
</div>

<style>
	.timeline {
		display: flex;
		flex-direction: column;
		gap: 6px;
		width: 100%;
	}

	canvas {
		display: block;
		width: 100%;
		cursor: crosshair;
		touch-action: none;
		border-radius: 8px;
	}

	.legend {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		font-size: 11px;
		letter-spacing: 0.02em;
	}
</style>
