/**
 * 生成《ERP 财务数据契约治理平台 · 项目答辩》PPTX
 * 用法：NODE_PATH=<workspace>/node_modules node build.js <out.pptx>
 */
const R = require("./render.js");
const { P, C, F, W, H, MX, CW, CY, NY, linesFor, fitFont, fillFont, needH, pageBase, noteCard, footer, card } = R;

const A = require("./content_a.js").pages;
const A2 = require("./content_a2.js").pages;
const B = require("./content_b.js").pages;
const Cc = require("./content_c.js").pages;
const ALL = [].concat(A, A2, B, Cc);

const pres = new P();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.author = "ERP 数据契约项目";
pres.title = "ERP 财务数据契约治理平台 · 项目答辩";

const BODY_H = 4.08;      // CY -> 5.42
const NOTE_TOP_MAX = NY;  // 讲稿卡起点上限

// ---------------------------------------------------------------- 要点列表
function addPoints(slide, points, x, y, w, h, opt) {
  if (!points || !points.length) return 0;
  const pad = 0.24;
  const iw = w - pad * 2 - 0.30;
  let pt = 13.5;
  let need = 0.32;
  const calc = (p0) => {
    let n = 0.32;
    for (const s of points) n += linesFor(s, iw, p0) * (p0 * 1.40 / 72) + 0.05;
    return n;
  };
  while (pt > 9.5 && calc(pt) > h + 0.30) pt -= 0.5;
  need = Math.min(calc(pt), h + 0.45);
  slide.addShape("roundRect", {
    x, y, w, h: need, rectRadius: 0.05,
    fill: { color: (opt && opt.fill) || C.ICE2 }, line: { color: C.LINE, width: 0.75 },
  });
  const runs = points.map((p, i) => ({
    text: p,
    options: {
      bullet: { code: "25AA" }, breakLine: i < points.length - 1,
      fontSize: pt, color: C.TEXT, fontFace: F.B, paraSpaceAfter: 4,
    },
  }));
  slide.addText(runs, { x: x + pad, y: y + 0.16, w: w - pad * 2, h: need - 0.24, valign: "top", margin: 0 });
  return need;
}

// 卡片所需高度（用于让卡片贴合内容，避免大框小字）
function cardNeedH(title, body, wIn, maxPt = 10.5) {
  let h = 0.18;
  if (title) h += 0.72;
  if (body) h += needH(body, wIn - 0.48, maxPt) + 0.18;
  return h;
}

// ---------------------------------------------------------------- 布局：grid
function layGrid(slide, p) {
  const d = p.d, n = d.cols || 3, items = d.items;
  let hasP = !!(d.points && d.points.length);
  if (hasP && items.length >= 6) {
    // 6 张以上卡片已占满版面：要点并入讲稿，保证内容不丢
    p.n = (p.n || "") + "补充要点：" + d.points.join("；") + "。";
    hasP = false;
    d.points = [];
  }
  const pH = hasP ? 1.02 : 0;
  const areaH = BODY_H - pH - (hasP ? 0.12 : 0);
  const rows = Math.ceil(items.length / n);
  const gap = 0.16;
  const cw = (CW - gap * (n - 1)) / n;
  let ch = (areaH - gap * (rows - 1)) / rows;
  // 卡片高度贴合内容（最多到区域高度）
  let need = 0;
  items.forEach((it) => { need = Math.max(need, cardNeedH(it.t, it.d, cw)); });
  ch = Math.min(ch, Math.max(need, 1.05));
  if (!hasP) ch = Math.min(ch, (BODY_H - gap * (rows - 1)) / rows);
  items.forEach((it, i) => {
    const r = Math.floor(i / n), c = i % n;
    card(slide, {
      x: MX + c * (cw + gap), y: CY + r * (ch + gap), w: cw, h: ch,
      fill: it.fill || C.ICE, title: it.t, body: it.d,
      tSize: n === 3 ? 14.5 : 15.5, tColor: it.tc || C.INK, bodyMax: n === 3 ? 12.5 : 13.5,
    });
  });
  let bottom = CY + rows * ch + (rows - 1) * gap;
  if (hasP) { addPoints(slide, d.points, MX, bottom + 0.12, CW, pH); bottom += 0.12 + pH; }
  return bottom;
}

// ---------------------------------------------------------------- 布局：steps
function laySteps(slide, p) {
  const d = p.d, items = d.items, n = items.length;
  const gap = 0.10;
  const ch = (BODY_H - gap * (n - 1)) / n;
  items.forEach((it, i) => {
    const y = CY + i * (ch + gap);
    slide.addShape("roundRect", { x: MX, y, w: CW, h: ch, rectRadius: 0.05, fill: { color: C.ICE2 }, line: { color: C.LINE, width: 0.75 } });
    slide.addShape("ellipse", { x: MX + 0.18, y: y + (ch - 0.32) / 2, w: 0.32, h: 0.32, fill: { color: C.INK } });
    slide.addText(String(i + 1), {
      x: MX + 0.18, y: y + (ch - 0.32) / 2, w: 0.32, h: 0.32, fontSize: 11.5, bold: true,
      color: C.WHITE, align: "center", valign: "middle", fontFace: F.B, margin: 0,
    });
    const tx = MX + 0.60, tw = 3.0;
    const tp = fillFont(it.t, tw, ch - 0.16, 11.5, 15);
    slide.addText(it.t, { x: tx, y: y + 0.06, w: tw, h: ch - 0.12, fontSize: tp, bold: true, color: C.INK, fontFace: F.H, valign: "middle", margin: 0 });
    const bx = MX + 3.72, bw = CW - 3.72 - 0.28;
    const bp = fillFont(it.d, bw, ch - 0.22, 10, 14);
    slide.addText(it.d, { x: bx, y: y + 0.10, w: bw, h: ch - 0.20, fontSize: bp, color: C.TEXT, fontFace: F.B, valign: "middle", margin: 0, lineSpacing: bp * 1.36 });
  });
  return CY + BODY_H;
}

// ---------------------------------------------------------------- 布局：flow
function layFlow(slide, p) {
  const d = p.d, nodes = d.nodes;
  const nH = 1.90, nY = CY;
  const gap = 0.14;
  const nW = (CW - gap * (nodes.length - 1)) / nodes.length;
  nodes.forEach((nd, i) => {
    const x = MX + i * (nW + gap);
    const isHl = d.hl === i;
    slide.addShape("roundRect", {
      x, y: nY, w: nW, h: nH, rectRadius: 0.06,
      fill: { color: isHl ? C.INK : C.ICE }, line: { color: isHl ? C.INK : C.LINE, width: 0.75 },
    });
    slide.addShape("ellipse", { x: x + 0.16, y: nY + 0.16, w: 0.30, h: 0.30, fill: { color: isHl ? C.GOLD : C.STEEL } });
    slide.addText(String(i + 1), {
      x: x + 0.16, y: nY + 0.16, w: 0.30, h: 0.30, fontSize: 11, bold: true, color: C.WHITE,
      align: "center", valign: "middle", fontFace: F.B, margin: 0,
    });
    const tp = fillFont(nd.t, nW - 0.34, 0.52, 11, 13.5);
    slide.addText(nd.t, { x: x + 0.17, y: nY + 0.50, w: nW - 0.34, h: 0.54, fontSize: tp, bold: true, color: isHl ? C.WHITE : C.INK, fontFace: F.H, valign: "middle", margin: 0 });
    const bp = fillFont(nd.d, nW - 0.36, nH - 1.14, 9.5, 12.5);
    slide.addText(nd.d, { x: x + 0.18, y: nY + 1.08, w: nW - 0.36, h: nH - 1.16, fontSize: bp, color: isHl ? "D6E2F0" : C.TEXT, fontFace: F.B, valign: "top", margin: 0, lineSpacing: bp * 1.34 });
    if (i < nodes.length - 1) {
      slide.addShape("rightTriangle", { x: x + nW + 0.015, y: nY + nH / 2 - 0.09, w: 0.12, h: 0.18, fill: { color: C.GOLD }, line: { width: 0 } });
    }
  });
  const bY = CY + nH + 0.20, bH = BODY_H - nH - 0.20;
  const bw = (CW - 0.20) / 2;
  if (d.left) card(slide, { x: MX, y: bY, w: bw, h: bH, fill: d.left.fill || C.ICE, title: d.left.t, body: d.left.d, tSize: 14.5, tColor: d.left.tc });
  if (d.right) card(slide, { x: MX + bw + 0.20, y: bY, w: bw, h: bH, fill: d.right.fill || C.ICE, title: d.right.t, body: d.right.d, tSize: 14.5, tColor: d.right.tc });
  return CY + BODY_H;
}

// ---------------------------------------------------------------- 布局：compare
function layCompare(slide, p) {
  const d = p.d;
  const hasP = !!(d.points && d.points.length);
  const pH = hasP ? 1.32 : 0;
  const areaH = BODY_H - pH - (hasP ? 0.12 : 0);
  const bw = (CW - 0.22) / 2;
  let cH = areaH;
  if (!hasP) {
    const need = Math.max(cardNeedH(d.left.t, d.left.d, bw), cardNeedH(d.right.t, d.right.d, bw));
    cH = Math.min(areaH, Math.max(need, 1.30));
  }
  card(slide, { x: MX, y: CY, w: bw, h: cH, fill: d.left.fill || C.ICE, title: d.left.t, body: d.left.d, tSize: 16, tColor: d.left.tc });
  card(slide, { x: MX + bw + 0.22, y: CY, w: bw, h: cH, fill: d.right.fill || C.ICE, title: d.right.t, body: d.right.d, tSize: 16, tColor: d.right.tc });
  let bottom = CY + cH;
  if (hasP) { addPoints(slide, d.points, MX, bottom + 0.12, CW, pH); bottom += 0.12 + pH; }
  return bottom;
}

// ---------------------------------------------------------------- 布局：table
function layTable(slide, p) {
  const d = p.d;
  const hasP = !!(d.points && d.points.length);
  const pH = hasP ? 1.25 : 0;
  const tH = BODY_H - pH - (hasP ? 0.12 : 0);
  const rows = [d.head].concat(d.rows);
  const nRow = rows.length;
  const rowH = tH / nRow;
  let fs = nRow > 6 ? 11.5 : 13;
  const mk = (r, ri) => r.map((cell) => ({
    text: String(cell),
    options: {
      fontSize: fs, color: ri === 0 ? C.WHITE : C.TEXT, bold: ri === 0,
      fontFace: F.B, valign: "middle", align: ri === 0 ? "center" : "left",
    },
  }));
  slide.addTable(rows.map((r, ri) => mk(r, ri)), {
    x: MX, y: CY, w: CW, rowH, border: { type: "solid", color: C.LINE, pt: 0.75 },
    fill: { color: C.ICE2 }, autoPage: false, valign: "middle", margin: [0.05, 0.14, 0.05, 0.14],
  });
  slide.addShape("rect", { x: MX, y: CY, w: CW, h: rowH, fill: { color: C.INK } });
  slide.addTable([mk(d.head, 0)], {
    x: MX, y: CY, w: CW, rowH, border: { type: "solid", color: C.INK, pt: 0.75 },
    fill: { color: C.INK }, autoPage: false, valign: "middle", margin: [0.05, 0.14, 0.05, 0.14],
  });
  let bottom = CY + tH;
  if (hasP) { addPoints(slide, d.points, MX, bottom + 0.12, CW, pH); bottom += 0.12 + pH; }
  return bottom;
}

// ---------------------------------------------------------------- 布局：chart
function layChart(slide, pres, p) {
  const d = p.d;
  const cW = CW * 0.50, cH = BODY_H - 0.06;
  slide.addShape("roundRect", { x: MX, y: CY, w: cW, h: cH, rectRadius: 0.05, fill: { color: C.ICE2 }, line: { color: C.LINE, width: 0.75 } });
  slide.addChart(pres.ChartType.bar,
    [{ name: "检查项数", labels: d.chart.labels, values: d.chart.values }],
    {
      x: MX + 0.14, y: CY + 0.18, w: cW - 0.28, h: cH - 0.44,
      barDir: "col", showTitle: true, title: "契约检查项演进（25 → 72）", titleFontSize: 12, titleColor: C.INK,
      showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 10, dataLabelColor: C.INK,
      chartColors: ["1B4F72", "2E5F8A", "D9973A", "2C7A5B", "0E2A47"],
      catAxisLabelColor: C.GREY, valAxisLabelColor: C.GREY, catAxisLabelFontSize: 10, valAxisLabelFontSize: 10,
      valGridLine: { color: "E3E9F0", size: 0.5 }, catGridLine: { style: "none" },
      showLegend: false, valAxisMaxVal: 80,
    });
  addPoints(slide, d.points, MX + cW + 0.20, CY, CW - cW - 0.20, BODY_H - 0.06);
  return CY + BODY_H;
}

// ---------------------------------------------------------------- 布局：stats
function layStats(slide, p) {
  const d = p.d, items = d.items;
  const n = items.length, cols = n > 4 ? 3 : 2;
  const rows = Math.ceil(n / cols);
  const gap = 0.16;
  const cw = (CW - gap * (cols - 1)) / cols;
  const hasP = !!(d.points && d.points.length);
  const pH = hasP ? 1.10 : 0;
  const areaH = BODY_H - pH - (hasP ? 0.12 : 0);
  const ch = (areaH - gap * (rows - 1)) / rows;
  items.forEach((it, i) => {
    const r = Math.floor(i / cols), c = i % cols;
    const x = MX + c * (cw + gap), y = CY + r * (ch + gap);
    slide.addShape("roundRect", { x, y, w: cw, h: ch, rectRadius: 0.06, fill: { color: C.ICE }, line: { color: C.LINE, width: 0.75 } });
    // 卡内空间按比例分配：数字 → 标签 → 说明，避免说明区被挤没
    let numH = Math.min(0.72, ch * 0.46);
    let labH = 0.26;
    if (ch - (0.10 + numH + labH) - 0.12 < 0.24) { numH = Math.max(0.42, ch * 0.36); labH = 0.24; }
    const descTop = 0.10 + numH + labH;
    const descH = Math.max(0.24, ch - descTop - 0.12);
    const vp = fillFont(it.v, cw - 0.40, numH, 18, 38);
    slide.addText(it.v, { x: x + 0.20, y: y + 0.08, w: cw - 0.40, h: numH, fontSize: vp, bold: true, color: C.INK, fontFace: F.H, valign: "middle", margin: 0 });
    const lp = fillFont(it.l, cw - 0.40, labH, 10, 12.5);
    slide.addText(it.l, { x: x + 0.20, y: y + 0.08 + numH, w: cw - 0.40, h: labH, fontSize: lp, bold: true, color: C.GOLD, fontFace: F.B, valign: "middle", margin: 0 });
    if (it.d) {
      const bp = fillFont(it.d, cw - 0.40, descH, 9.5, 13);
      slide.addText(it.d, { x: x + 0.20, y: y + descTop, w: cw - 0.40, h: descH, fontSize: bp, color: C.GREY, fontFace: F.B, valign: "top", margin: 0, lineSpacing: bp * 1.32 });
    }
  });
  let bottom = CY + rows * ch + (rows - 1) * gap;
  if (hasP) { addPoints(slide, d.points, MX, bottom + 0.12, CW, pH); bottom += 0.12 + pH; }
  return bottom;
}

// ---------------------------------------------------------------- 布局：timeline
function layTimeline(slide, p) {
  const d = p.d, items = d.items;
  let hasP = !!(d.points && d.points.length);
  if (hasP && items.length >= 6) {
    // 6 项以上时间线已占满版面：要点并入讲稿，保证内容不丢
    p.n = (p.n || "") + "补充要点：" + d.points.join("；") + "。";
    hasP = false;
    d.points = [];
  }
  const pH = hasP ? 1.28 : 0;
  const areaH = BODY_H - pH - (hasP ? 0.12 : 0);
  const gap = 0.12;
  const ch = (areaH - gap * (items.length - 1)) / items.length;
  items.forEach((it, i) => {
    const y = CY + i * (ch + gap);
    slide.addShape("roundRect", { x: MX, y, w: CW, h: ch, rectRadius: 0.05, fill: { color: it.bad ? C.REDBG : C.ICE2 }, line: { color: it.bad ? "EBC9C7" : C.LINE, width: 0.75 } });
    slide.addShape("ellipse", { x: MX + 0.20, y: y + (ch - 0.34) / 2, w: 0.34, h: 0.34, fill: { color: it.bad ? C.RED : C.GREEN } });
    slide.addText(String(it.tag || i + 1), {
      x: MX + 0.20, y: y + (ch - 0.34) / 2, w: 0.34, h: 0.34, fontSize: 12, bold: true, color: C.WHITE,
      align: "center", valign: "middle", fontFace: F.B, margin: 0,
    });
    const tp = fillFont(it.t, 3.10, ch - 0.16, 11.5, 15);
    slide.addText(it.t, { x: MX + 0.66, y: y + 0.06, w: 3.10, h: ch - 0.12, fontSize: tp, bold: true, color: it.bad ? C.RED : C.INK, fontFace: F.H, valign: "middle", margin: 0 });
    const bw = CW - 3.98 - 0.28;
    const bp = fillFont(it.d, bw, ch - 0.20, 10, 13.5);
    slide.addText(it.d, { x: MX + 3.86, y: y + 0.10, w: bw, h: ch - 0.18, fontSize: bp, color: C.TEXT, fontFace: F.B, valign: "middle", margin: 0, lineSpacing: bp * 1.36 });
  });
  let bottom = CY + items.length * ch + (items.length - 1) * gap;
  if (hasP) { addPoints(slide, d.points, MX, bottom + 0.12, CW, pH); bottom += 0.12 + pH; }
  return bottom;
}

// ---------------------------------------------------------------- 布局：diagram
function layDiagram(slide, p) {
  const d = p.d;
  const hasP = !!(d.points && d.points.length);
  const pH = hasP ? 1.02 : 0;
  const areaH = BODY_H - pH - (hasP ? 0.12 : 0);
  (d.boxes || []).forEach((b) => {
    if (!b.t && !b.d) return;
    const x = MX + b.x * CW, y = CY + b.y * areaH, w = b.w * CW, h = b.h * areaH;
    slide.addShape("roundRect", { x, y, w, h, rectRadius: 0.05, fill: { color: b.fill || C.ICE }, line: { color: C.LINE, width: 0.75 } });
    if (b.t) {
      const tp = fillFont(b.t, w - 0.32, 0.52, 11, 13.5);
      slide.addText(b.t, { x: x + 0.16, y: y + 0.08, w: w - 0.32, h: 0.54, fontSize: tp, bold: true, color: b.fc || C.INK, fontFace: F.H, valign: "middle", margin: 0 });
    }
    if (b.d) {
      const bp = fillFont(b.d, w - 0.32, h - 0.62, 9, 11);
      slide.addText(b.d, { x: x + 0.16, y: y + 0.62, w: w - 0.32, h: h - 0.64, fontSize: bp, color: b.fc === "FFFFFF" ? "D6E2F0" : C.TEXT, fontFace: F.B, valign: "top", margin: 0, lineSpacing: bp * 1.32 });
    }
  });
  let bottom = CY + areaH;
  if (d.note) {
    slide.addText(d.note, { x: MX, y: bottom - 0.30, w: CW, h: 0.30, fontSize: 12, italic: true, color: C.STEEL, fontFace: F.B, valign: "middle", margin: 0 });
  }
  if (hasP) { addPoints(slide, d.points, MX, bottom + 0.12, CW, pH); bottom += 0.12 + pH; }
  return bottom;
}

// ---------------------------------------------------------------- 布局：stack（层带）
function layStack(slide, p) {
  const d = p.d, layers = d.layers;
  const hasP = !!(d.points && d.points.length);
  const pH = hasP ? 1.05 : 0;
  const areaH = BODY_H - pH - (hasP ? 0.12 : 0);
  const gap = 0.12;
  const lh = (areaH - gap * (layers.length - 1)) / layers.length;
  layers.forEach((l, i) => {
    const y = CY + i * (lh + gap);
    slide.addShape("roundRect", { x: MX, y, w: CW, h: lh, rectRadius: 0.05, fill: { color: l.fill }, line: { width: 0 } });
    const tp = fillFont(l.t, 3.5, lh - 0.16, 12, 15.5);
    slide.addText(l.t, { x: MX + 0.26, y: y + 0.08, w: 3.5, h: lh - 0.16, fontSize: tp, bold: true, color: l.fc, fontFace: F.H, valign: "middle", margin: 0 });
    const bw = CW - 4.1 - 0.30;
    const bp = fillFont(l.d, bw, lh - 0.20, 10, 13.5);
    slide.addText(l.d, { x: MX + 4.00, y: y + 0.08, w: bw, h: lh - 0.16, fontSize: bp, color: l.fc === "FFFFFF" ? "D6E2F0" : C.TEXT, fontFace: F.B, valign: "middle", margin: 0, lineSpacing: bp * 1.36 });
  });
  let bottom = CY + layers.length * lh + (layers.length - 1) * gap;
  if (d.note) slide.addText(d.note, { x: MX, y: bottom + 0.06, w: CW, h: 0.28, fontSize: 12, italic: true, color: C.STEEL, fontFace: F.B, align: "center", valign: "middle", margin: 0 });
  if (hasP) { addPoints(slide, d.points, MX, bottom + (d.note ? 0.38 : 0.12), CW, pH); bottom += 0.12 + pH; }
  return bottom;
}

// ---------------------------------------------------------------- 布局：quote
function layQuote(slide, p) {
  const d = p.d;
  const qW = CW * 0.40;
  slide.addShape("roundRect", { x: MX, y: CY, w: qW, h: BODY_H, rectRadius: 0.06, fill: { color: C.INK } });
  slide.addShape("ellipse", { x: MX + qW - 1.0, y: CY + BODY_H - 1.0, w: 1.7, h: 1.7, fill: { color: "1B4F72" } });
  const qp = fillFont(d.quote, qW - 0.60, 1.22, 18, 30);
  slide.addText(d.quote, { x: MX + 0.30, y: CY + 0.36, w: qW - 0.60, h: 1.26, fontSize: qp, bold: true, color: C.GOLDL, fontFace: F.H, valign: "middle", margin: 0 });
  slide.addShape("ellipse", { x: MX + 0.32, y: CY + 1.76, w: 0.12, h: 0.12, fill: { color: C.GOLD } });
  const sp = fillFont(d.quoteSub, qW - 0.60, BODY_H - 2.10, 11, 14);
  slide.addText(d.quoteSub, { x: MX + 0.30, y: CY + 2.02, w: qW - 0.60, h: BODY_H - 2.22, fontSize: sp, color: "C7D6E8", fontFace: F.B, valign: "top", margin: 0, lineSpacing: sp * 1.42 });
  const px = MX + qW + 0.22;
  const gap = 0.12;
  const ph = (BODY_H - gap * (d.points.length - 1)) / d.points.length;
  d.points.forEach((pt, i) => {
    card(slide, { x: px, y: CY + i * (ph + gap), w: CW - qW - 0.22, h: ph, fill: C.ICE, body: pt });
  });
  return CY + BODY_H;
}

// ---------------------------------------------------------------- 布局：code
function layCode(slide, p) {
  const d = p.d;
  const cW = CW * 0.42;
  slide.addShape("roundRect", { x: MX, y: CY, w: cW, h: BODY_H, rectRadius: 0.05, fill: { color: "12293F" }, line: { width: 0 } });
  const codeText = d.code.map((l) => "  " + l).join("\n");
  slide.addText(codeText, {
    x: MX + 0.20, y: CY + 0.28, w: cW - 0.40, h: BODY_H - 0.56, fontSize: 13.5,
    fontFace: "Consolas", color: "BFD6EE", valign: "top", margin: 0, lineSpacing: 22,
  });
  const px = MX + cW + 0.22;
  const gap = 0.12;
  const ph = (BODY_H - gap * (d.points.length - 1)) / d.points.length;
  d.points.forEach((pt, i) => {
    card(slide, { x: px, y: CY + i * (ph + gap), w: CW - cW - 0.22, h: ph, fill: C.ICE, body: pt });
  });
  return CY + BODY_H;
}

// ---------------------------------------------------------------- 布局：qa
function layQa(slide, p) {
  const d = p.d, items = d.items;
  const gap = 0.12;
  const ch = (BODY_H - gap * (items.length - 1)) / items.length;
  items.forEach((it, i) => {
    const y = CY + i * (ch + gap);
    slide.addShape("roundRect", { x: MX, y, w: CW, h: ch, rectRadius: 0.05, fill: { color: C.ICE2 }, line: { color: C.LINE, width: 0.75 } });
    slide.addShape("ellipse", { x: MX + 0.18, y: y + 0.18, w: 0.26, h: 0.26, fill: { color: C.GOLD } });
    slide.addText("Q", { x: MX + 0.18, y: y + 0.18, w: 0.26, h: 0.26, fontSize: 10.5, bold: true, color: C.WHITE, align: "center", valign: "middle", fontFace: F.B, margin: 0 });
    const qp = fillFont(it.q, CW - 0.72, 0.34, 11.5, 14.5);
    slide.addText(it.q, { x: MX + 0.54, y: y + 0.13, w: CW - 0.72, h: 0.36, fontSize: qp, bold: true, color: C.INK, fontFace: F.H, valign: "middle", margin: 0 });
    const ap = fillFont(it.a, CW - 0.72, ch - 0.58, 10, 13);
    slide.addText(it.a, { x: MX + 0.54, y: y + 0.52, w: CW - 0.72, h: ch - 0.60, fontSize: ap, color: C.TEXT, fontFace: F.B, valign: "top", margin: 0, lineSpacing: ap * 1.36 });
  });
  return CY + BODY_H;
}

// ---------------------------------------------------------------- 结束页
function slideEnd(pres, o) {
  const s = pres.addSlide();
  s.background = { color: C.INK };
  s.addShape("ellipse", { x: W - 3.0, y: -1.8, w: 5.0, h: 5.0, fill: { color: "16365C" } });
  s.addShape("ellipse", { x: -1.6, y: H - 2.6, w: 4.0, h: 4.0, fill: { color: "123253" } });
  s.addText(o.title, { x: 1.1, y: 2.15, w: 9.0, h: 1.0, fontSize: 40, bold: true, color: C.WHITE, fontFace: F.H, valign: "middle", margin: 0 });
  s.addText(o.sub, { x: 1.1, y: 3.25, w: 9.0, h: 0.5, fontSize: 15, color: C.GOLDL, fontFace: F.B, valign: "middle", margin: 0 });
  s.addShape("ellipse", { x: 1.12, y: 4.00, w: 0.13, h: 0.13, fill: { color: C.GOLD } });
  let yy = 4.30;
  (o.points || []).forEach((t) => {
    s.addText(t, { x: 1.1, y: yy, w: 10.8, h: 0.38, fontSize: 12.5, color: "B9CBE0", fontFace: F.B, valign: "middle", margin: 0 });
    yy += 0.42;
  });
  s.addText(o.n, { x: 1.1, y: yy + 0.25, w: 10.8, h: 0.4, fontSize: 13, color: C.GOLDL, bold: true, fontFace: F.B, valign: "middle", margin: 0 });
  if (o.n) s.addNotes(o.n);
  return s;
}

// ---------------------------------------------------------------- 组装
let idx = 0;
const warnings = [];
ALL.forEach((p) => {
  idx += 1;
  if (p.lay === "cover") { R.slideCover(pres, p); return; }
  if (p.lay === "section") { R.slideSection(pres, p); return; }
  if (p.lay === "end") { slideEnd(pres, p); return; }

  const s = pres.addSlide();
  pageBase(s, { kicker: p.k, title: p.ti, sub: p.su, titleSize: 25 });
  let bottom = CY + BODY_H;
  switch (p.lay) {
    case "grid": bottom = layGrid(s, p); break;
    case "steps": bottom = laySteps(s, p); break;
    case "flow": bottom = layFlow(s, p); break;
    case "compare": bottom = layCompare(s, p); break;
    case "table": bottom = layTable(s, p); break;
    case "chart": bottom = layChart(s, pres, p); break;
    case "stats": bottom = layStats(s, p); break;
    case "timeline": bottom = layTimeline(s, p); break;
    case "diagram": bottom = layDiagram(s, p); break;
    case "stack": bottom = layStack(s, p); break;
    case "quote": bottom = layQuote(s, p); break;
    case "code": bottom = layCode(s, p); break;
    case "qa": bottom = layQa(s, p); break;
    default: warnings.push("unknown layout: " + p.lay); break;
  }
  const noteTop = Math.max(CY + 1.60, Math.min(bottom + 0.14, NOTE_TOP_MAX));
  noteCard(s, p.n || "", noteTop);
  footer(s, idx);
  if (p.n) s.addNotes(p.n);
});

if (warnings.length) console.log("WARN:", warnings.join(" | "));

const out = process.argv[2] || "<PPT工程目录>/deck/out.pptx";
pres.writeFile({ fileName: out }).then(() => {
  console.log("WROTE", out, "slides:", ALL.length);
});
