import { hierarchy, pack } from 'd3-hierarchy';
import { amount, type Catalog, type Item, type Kind, type Similarity } from './model';

interface Branch {
  item?: Item;
  children?: Branch[];
}
interface Dot {
  item: Item;
  x: number;
  y: number;
  r: number;
}
interface Edge {
  a: Dot;
  b: Dot;
  similarity: Similarity;
}
interface Point {
  x: number;
  y: number;
}
interface Camera extends Point {
  k: number;
  selection?: Item;
}
const clamp = (n: number, low: number, high: number) => Math.min(high, Math.max(low, n));
const fade = (n: number, low: number, high: number) => {
  const t = clamp((n - low) / (high - low), 0, 1);
  return t * t * (3 - 2 * t);
};

function layout(catalog: Catalog) {
  // Connected artists share a packing region within their genre.
  function region(group: Item): Branch {
    const remaining = new Map(group.children.map((a) => [a.name, a]));
    const components: Branch[] = [];
    for (const artist of group.children) {
      if (!remaining.delete(artist.name)) continue;
      const queue = [artist];
      for (const member of queue) {
        for (const other of catalog.neighbors.get(member.name)?.keys() ?? []) {
          const next = remaining.get(other);
          if (next) {
            queue.push(next);
            remaining.delete(other);
          }
        }
      }
      const members = queue.map((item) => ({
        item,
        children: item.children.map((track) => ({ item: track })),
      }));
      components.push(members.length > 1 ? { children: members } : members[0]);
    }
    return { item: group, children: components };
  }
  const tree = hierarchy<Branch>({ children: catalog.groupList.map(region) })
    .sum((d) => (d.item?.kind === 'track' ? d.item.total : 0))
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  const packed = pack<Branch>().size([1, 1])(tree);
  const byItem = new Map<Item, Dot>();
  const groups: Dot[] = [],
    artists: Dot[] = [];
  const scales: Record<Kind, number> = { group: Infinity, artist: Infinity, track: Infinity };
  for (const d of packed.descendants()) {
    const item = d.data.item;
    if (!item) continue;
    const dot = { item, x: d.x - 0.5, y: d.y - 0.5, r: d.r };
    byItem.set(item, dot);
    if (item.total) scales[item.kind] = Math.min(scales[item.kind], d.r / Math.sqrt(item.total));
    if (item.kind === 'group') groups.push(dot);
    if (item.kind === 'artist') artists.push(dot);
  }
  const byArtist = new Map<string, Dot>();
  for (const artist of artists) {
    const previous = byArtist.get(artist.item.name);
    if (!previous || previous.item.total < artist.item.total) byArtist.set(artist.item.name, artist);
  }
  const edges: Edge[] = [];
  for (const [name, near] of catalog.neighbors) {
    const a = byArtist.get(name);
    if (!a) continue;
    for (const [peer, similarity] of near) {
      const b = byArtist.get(peer);
      if (b && name < peer) edges.push({ a, b, similarity });
    }
  }
  return { groups, artists, edges, byArtist, byItem, scales };
}

const layouts = new WeakMap<Catalog, ReturnType<typeof layout>>();
const cameras = new WeakMap<HTMLCanvasElement, Camera>();

export function mountArtistAtlas(
  canvas: HTMLCanvasElement,
  catalog: Catalog,
  year: string,
  name: (item: Item) => string,
  format: (ms: number) => string,
  select: (item: Item) => void,
  relation: string,
  inferredLabel: (item: Item) => string,
  sharedTags: (a: Item, b: Item, tags: string[]) => string,
) {
  const geometry = layouts.get(catalog) ?? layout(catalog);
  layouts.set(catalog, geometry);
  const context = canvas.getContext('2d');
  if (!context) return { destroy() {}, focus(_item?: Item) {} };
  const ctx = context;
  const camera = cameras.get(canvas) ?? { x: 0, y: 0, k: 1 };
  cameras.set(canvas, camera);
  const frame = canvas.parentElement!;
  const ja = document.documentElement.lang === 'ja';
  const abort = new AbortController(),
    options = { signal: abort.signal };
  const controls = document.createElement('div'),
    readout = document.createElement('output');
  controls.className = 'atlas-controls';
  readout.className = 'atlas-readout';
  readout.hidden = true;
  frame.append(controls, readout);
  let w = 0,
    h = 0,
    unit = 0,
    rx = 0,
    ry = 0,
    pending = 0;
  let hover: Dot | undefined;
  let hoverEdge: Edge | undefined;
  const segments: { edge: Edge; p: Point; q: Point }[] = [];
  let motion: { start: Camera; end: Camera; time: number } | undefined;
  let marks: { dot: Dot; x: number; y: number; r: number }[] = [];
  const project = (d: Point) => ({
    x: w / 2 + (d.x - camera.x) * rx * camera.k,
    y: h / 2 + (d.y - camera.y) * ry * camera.k,
  });
  // Areas are proportional within each level. The fixed coordinates always use all years.
  function paint(now: number) {
    pending = 0;
    if (motion) {
      const t = fade(now - motion.time, 0, 330);
      camera.k = motion.start.k * Math.pow(motion.end.k / motion.start.k, t);
      // Interpolate the screen-space displacement as the scale changes.
      const blend =
        motion.start.k === motion.end.k
          ? t
          : (1 - motion.start.k / camera.k) / (1 - motion.start.k / motion.end.k);
      camera.x = motion.start.x + (motion.end.x - motion.start.x) * blend;
      camera.y = motion.start.y + (motion.end.y - motion.start.y) * blend;
      if (t >= 1) motion = undefined;
      else redraw();
    }
    const style = getComputedStyle(canvas),
      ink = style.getPropertyValue('--ink').trim(),
      paper = style.getPropertyValue('--paper').trim();
    const palette = Array.from({ length: 8 }, (_, i) =>
      style.getPropertyValue('--mm-color-' + i).trim(),
    );
    const artistsOpacity = fade(Math.log2(camera.k), 0.25, 1.45);
    const active = (d: Dot) => amount(d.item, year) > 0;
    ctx.clearRect(0, 0, w, h);
    marks = [];
    segments.length = 0;
    const labels: { dot: Dot; x: number; y: number; r: number; alpha: number; priority: number }[] = [];
    function draw(d: Dot, opacity: number, labelOpacity: number, clickable: boolean) {
      if (opacity < 0.015 || !active(d)) return;
      const { x, y } = project(d);
      const r = geometry.scales[d.item.kind] * Math.sqrt(amount(d.item, year)) * unit * camera.k;
      if (x + r < 0 || y + r < 0 || x - r > w || y - r > h) return;
      ctx.fillStyle = palette[d.item.color % 8];
      ctx.globalAlpha = opacity;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fill();
      if (clickable) marks.push({ dot: d, x, y, r });
      if (r > 4 && labelOpacity > 0.04)
        labels.push({ dot: d, x, y, r, alpha: labelOpacity, priority: r * labelOpacity });
    }
    for (const g of geometry.groups)
      draw(g, 0.73 * (1 - artistsOpacity) + 0.045, 1 - artistsOpacity, artistsOpacity < 0.5);
    if (artistsOpacity > 0.01) {
      ctx.strokeStyle = ink;
      ctx.lineWidth = 1;
      ctx.beginPath();
      const inFrame = (p: Point) => p.x >= 0 && p.x <= w && p.y >= 0 && p.y <= h;
      for (const edge of geometry.edges) {
        if (!active(edge.a) || !active(edge.b)) continue;
        const p = project(edge.a), q = project(edge.b);
        if (!inFrame(p) && !inFrame(q)) continue;
        segments.push({ edge, p, q });
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(q.x, q.y);
      }
      ctx.globalAlpha = artistsOpacity * (segments.length > 100 ? 0.28 : 0.5);
      ctx.stroke();
      const selected = camera.selection?.kind === 'track' ? camera.selection.parent : camera.selection;
      const highlight = hover?.item.kind === 'artist' ? hover.item.name : selected?.kind === 'artist' ? selected.name : undefined;
      if (hoverEdge || highlight) {
        ctx.globalAlpha = artistsOpacity * 0.95;
        ctx.strokeStyle = style.getPropertyValue('--accent').trim();
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (const { edge, p, q } of segments) {
          if (hoverEdge ? edge !== hoverEdge : edge.a.item.name !== highlight && edge.b.item.name !== highlight) continue;
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
        }
        ctx.stroke();
      }
      for (const a of geometry.artists) {
        if (!active(a)) continue;
        const bounds = a.r * unit * camera.k,
          p = project(a);
        if (
          p.x + (bounds * rx) / unit < 0 ||
          p.x - (bounds * rx) / unit > w ||
          p.y + (bounds * ry) / unit < 0 ||
          p.y - (bounds * ry) / unit > h
        )
          continue;
        const detail = fade(bounds, 68, 132) * fade(camera.k, 2.8, 5);
        draw(
          a,
          artistsOpacity * (0.83 - 0.78 * detail),
          artistsOpacity * (1 - detail),
          artistsOpacity >= 0.5 && detail < 0.5,
        );
        if (detail > 0.015)
          for (const t of a.item.children)
            draw(geometry.byItem.get(t)!, detail * 0.91, detail, detail >= 0.5);
      }
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    ctx.lineWidth = 3;
    const placed: { x: number; y: number; width: number }[] = [];
    for (const { dot, x, y, r, alpha } of labels.sort((a, b) => b.priority - a.priority)) {
      const group = dot.item.kind === 'group',
        text = name(dot.item);
      ctx.font = (group ? '600 14' : '500 12') + 'px system-ui, sans-serif';
      const width = ctx.measureText(text).width,
        yy = group ? y : y + Math.min(r, 22) + 8;
      if (
        x - width / 2 < 2 ||
        x + width / 2 > w - 2 ||
        yy > h - 8 ||
        yy < 8 ||
        placed.some((b) => Math.abs(b.y - yy) < 18 && Math.abs(b.x - x) < (b.width + width) / 2 + 6)
      )
        continue;
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = paper;
      ctx.strokeText(text, x, yy);
      ctx.fillStyle = ink;
      ctx.fillText(text, x, yy);
      placed.push({ x, y: yy, width });
    }
    ctx.globalAlpha = 1;
    if (hover) {
      const m = marks.find((m) => m.dot === hover);
      if (m) {
        ctx.strokeStyle = ink;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(m.x, m.y, m.r + 2, 0, 2 * Math.PI);
        ctx.stroke();
      }
    }
  }
  function redraw() {
    if (!pending) pending = requestAnimationFrame(paint);
  }
  function resize() {
    w = canvas.clientWidth;
    h = canvas.clientHeight;
    rx = w * 0.94;
    ry = h * 0.94;
    unit = Math.min(rx, ry);
    const dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    redraw();
  }
  function show(d?: Dot, edge?: Edge) {
    hover = d;
    hoverEdge = edge;
    const item = d?.item ?? camera.selection;
    readout.hidden = !item && !edge;
    if (item) {
      const parts = [name(item), item.credit, format(amount(item, year)), inferredLabel(item)].filter(Boolean);
      readout.textContent = (d ? '' : ja ? '選択中 · ' : 'Selected · ') + parts.join(' · ');
    }
    if (edge) {
      const pair = name(edge.a.item) + ' ↔ ' + name(edge.b.item);
      const tags = edge.similarity.tags;
      readout.textContent = tags.length ? pair + (ja ? ' ｜ 共通タグ · ' : ' | Shared tags · ') + sharedTags(edge.a.item, edge.b.item, tags) : pair;
    }
    redraw();
  }
  function animate(end: Camera) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      motion = undefined;
      Object.assign(camera, end);
    } else motion = { start: { ...camera }, end, time: performance.now() };
    show();
  }
  function focus(item?: Item) {
    camera.selection = item;
    if (!item) {
      animate({ x: 0, y: 0, k: 1 });
      return;
    }
    const d = geometry.byItem.get(item) ?? geometry.byArtist.get(item.name);
    if (!d) return;
    let bounds = d;
    while (!bounds.r && bounds.item.parent) bounds = geometry.byItem.get(bounds.item.parent)!;
    animate({
        x: d.x,
        y: d.y,
        k: clamp(
          (item.kind === 'group' ? 0.42 : 0.36) / (bounds.r || 0.5),
          item.kind === 'group' ? 2.5 : 5,
          16384,
        ),
      });
  }
  function zoom(factor: number, x = w / 2, y = h / 2, smooth = false) {
    const k = clamp(camera.k * factor, 1, 16384);
    const end =
      k === 1
        ? { x: 0, y: 0, k }
        : {
            x: camera.x + ((x - w / 2) / rx) * (1 / camera.k - 1 / k),
            y: camera.y + ((y - h / 2) / ry) * (1 / camera.k - 1 / k),
            k,
          };
    if (smooth) animate(end);
    else {
      motion = undefined;
      Object.assign(camera, end);
      show();
    }
  }
  for (const [label, desc, run] of [
    ['+', ja ? '拡大' : 'Zoom in', () => zoom(1.75, w / 2, h / 2, true)],
    ['−', ja ? '縮小' : 'Zoom out', () => zoom(1 / 1.75, w / 2, h / 2, true)],
    ['⌂', ja ? '全体を表示' : 'Fit map', () => focus()],
  ] as const) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.ariaLabel = desc;
    b.title = desc;
    b.onclick = run;
    controls.append(b);
  }
  function nearest(x: number, y: number) {
    let best: Dot | undefined,
      dist = Infinity;
    for (const m of marks) {
      const delta = Math.hypot(x - m.x, y - m.y);
      if (delta <= Math.max(4, m.r) && delta < dist) {
        best = m.dot;
        dist = delta;
      }
    }
    return best;
  }
  function nearestEdge(x: number, y: number, tolerance: number) {
    let closest: Edge | undefined;
    let best = tolerance * tolerance;
    for (const { edge, p, q } of segments) {
      const dx = q.x - p.x, dy = q.y - p.y;
      const length = dx * dx + dy * dy;
      if (!length) continue;
      const t = clamp(((x - p.x) * dx + (y - p.y) * dy) / length, 0, 1);
      const squared = (x - p.x - t * dx) ** 2 + (y - p.y - t * dy) ** 2;
      if (squared < best) {
        closest = edge;
        best = squared;
      }
    }
    return closest;
  }
  const points = new Map<number, Point>();
  let tap: Point | undefined;
  function gesture() {
    const [a, b] = points.values();
    return b
      ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) }
      : { ...a, d: 0 };
  }
  canvas.tabIndex = 0;
  canvas.setAttribute(
    'aria-label',
    (ja ? '音楽遍歴のズーム地図。' : 'Zoomable listening map. ') + relation,
  );
  canvas.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      zoom(Math.exp(-clamp(e.deltaY, -250, 250) * 0.003), e.offsetX, e.offsetY);
    },
    { ...options, passive: false },
  );
  canvas.addEventListener(
    'pointerdown',
    (e) => {
      motion = undefined;
      canvas.setPointerCapture(e.pointerId);
      points.set(e.pointerId, { x: e.offsetX, y: e.offsetY });
      tap = points.size === 1 ? { x: e.offsetX, y: e.offsetY } : undefined;
    },
    options,
  );
  canvas.addEventListener(
    'pointermove',
    (e) => {
      if (!points.has(e.pointerId)) {
        if (!points.size) {
          const dot = nearest(e.offsetX, e.offsetY);
          const edge = dot ? undefined : nearestEdge(e.offsetX, e.offsetY, 4);
          if (hover !== dot || hoverEdge !== edge) show(dot, edge);
        }
        return;
      }
      const before = gesture();
      points.set(e.pointerId, { x: e.offsetX, y: e.offsetY });
      const after = gesture();
      if (tap && Math.hypot(tap.x - e.offsetX, tap.y - e.offsetY) > 5) tap = undefined;
      camera.x -= (after.x - before.x) / (rx * camera.k);
      camera.y -= (after.y - before.y) / (ry * camera.k);
      if (before.d > 0 && after.d > 0) zoom(after.d / before.d, after.x, after.y);
      else show();
    },
    options,
  );
  canvas.addEventListener(
    'pointerup',
    (e) => {
      if (!points.delete(e.pointerId)) return;
      if (tap) {
        const hit = nearest(e.offsetX, e.offsetY);
        if (hit) select(hit.item);
        else show(undefined, nearestEdge(e.offsetX, e.offsetY, e.pointerType === 'touch' ? 10 : 4));
      }
      tap = undefined;
    },
    options,
  );
  canvas.addEventListener(
    'pointercancel',
    (e) => {
      points.delete(e.pointerId);
      tap = undefined;
    },
    options,
  );
  canvas.addEventListener('pointerleave', e => {
    if (e.pointerType !== 'touch') show();
  }, options);
  canvas.addEventListener(
    'keydown',
    (e) => {
      if (e.key === '+' || e.key === '=') zoom(1.6);
      else if (e.key === '-') zoom(1 / 1.6);
      else if (e.key === 'Home') focus();
      else if (e.key === 'Escape') show();
      else if (e.key === 'Enter') {
        const d = hover ?? nearest(w / 2, h / 2);
        if (d) select(d.item);
      } else if (e.key.startsWith('Arrow')) {
        motion = undefined;
        camera.x +=
          ((Number(e.key === 'ArrowRight') - Number(e.key === 'ArrowLeft')) * 45) / (rx * camera.k);
        camera.y +=
          ((Number(e.key === 'ArrowDown') - Number(e.key === 'ArrowUp')) * 45) / (ry * camera.k);
        show();
      } else return;
      e.preventDefault();
    },
    options,
  );
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  const theme = new MutationObserver(redraw);
  theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redraw, options);
  resize();
  show();
  return {
    focus,
    destroy() {
      abort.abort();
      observer.disconnect();
      theme.disconnect();
      cancelAnimationFrame(pending);
      controls.remove();
      readout.remove();
    },
  };
}
