/**
 * 渲染引擎：ERP 财务数据契约治理平台 · 项目答辩
 * 风格参照「行业研报/金融商务」模板：深墨蓝封面与章节页 + 浅底内容页 + 金色强调 + 卡片式信息密度
 */
const P = require("pptxgenjs");

// ---------------------------------------------------------------- 配色
const C = {
  INK: "0E2A47",      // 深墨蓝（封面/章节页/深色卡）
  NAVY: "16365C",
  BLUE: "1B4F72",
  STEEL: "2E5F8A",
  ICE: "E4EDF7",      // 卡片浅蓝底
  ICE2: "F2F6FB",     // 更浅底
  GOLD: "D9973A",     // 强调金
  GOLDL: "F2C879",
  RED: "B33A36",
  REDBG: "FBEAE9",
  GREEN: "2C7A5B",
  GREENBG: "E8F3EE",
  GREY: "63758A",
  TEXT: "1B2733",
  WHITE: "FFFFFF",
  LINE: "D3DEEA",
};
const F = { H: "Microsoft YaHei", B: "Microsoft YaHei" };

// ---------------------------------------------------------------- 版式常量
const W = 13.3, H = 7.5;
const MX = 0.55;                 // 左右安全边距
const CW = W - MX * 2;           // 内容宽度 12.2
const TY = 0.34, TH = 0.58;      // 标题
const SY = 0.92, SH = 0.30;      // 副标题
const CY = 1.34;                 // 内容区起点
const CB = 5.42;                 // 内容区默认底
const NY = 5.60;                 // 讲稿卡起点

// ---------------------------------------------------------------- 文字度量
// 中文按 1em 宽估算，英文/数字按 0.55em；保守系数 1.06
function textWidthIn(str, pt) {
  let cn = 0, en = 0;
  for (const ch of String(str)) cn += ch.codePointAt(0) > 0x2000 ? 1 : 0.55;
  return ((cn * pt) / 72) * 1.06;
}
function linesFor(str, wIn, pt) {
  const perLine = Math.max(4, Math.floor(wIn / (pt / 72 * 1.06)));
  let units = 0;
  for (const ch of String(str)) units += ch.codePointAt(0) > 0x2000 ? 1 : 0.55;
  return Math.max(1, Math.ceil(units / perLine));
}
// 在给定高度内自适应字号（只缩不小）
function fitFont(str, wIn, hIn, prefer, min = 9) {
  let pt = prefer;
  while (pt > min) {
    const need = needH(str, wIn, pt);
    if (need <= hIn) break;
    pt -= 0.5;
  }
  return pt;
}
// 尽量填满容器：在 [min, max] 内取能容纳的最大字号（解决「大框小字留白」）
function fillFont(str, wIn, hIn, min = 10, max = 15) {
  let best = min;
  for (let pt = max; pt >= min; pt -= 0.5) {
    if (needH(str, wIn, pt) <= hIn) { best = pt; break; }
  }
  return best;
}
// 估算某段文字在给定宽度、字号下需要的高度（宽度留 0.12in 余量，行高系数 1.46）
function needH(str, wIn, pt) {
  return linesFor(str, Math.max(wIn - 0.20, 0.3), pt) * pt * 1.58 / 72;
}

// ---------------------------------------------------------------- 通用组件
function pageBase(slide, o) {
  slide.background = { color: C.WHITE };
  if (o.kicker) {
    slide.addText(o.kicker, {
      x: MX, y: 0.30, w: CW, h: 0.22, fontSize: 10.5, color: C.GOLD, bold: true,
      fontFace: F.B, charSpacing: 1.2, valign: "middle",
    });
  }
  const tY = o.kicker ? TY + 0.16 : TY;
  const tPt = fillFont(o.title, CW - 1.4, 0.70, 15, o.titleSize || 26);
  slide.addText(o.title, {
    x: MX, y: tY, w: CW - 1.2, h: 0.72, fontSize: tPt, bold: true,
    color: C.INK, fontFace: F.H, valign: "middle", margin: 0,
  });
  // 右上角的圆形序号徽章（贯穿全篇的视觉母题）
  if (o.badge) {
    slide.addShape("ellipse", { x: W - MX - 0.62, y: tY + 0.03, w: 0.56, h: 0.56, fill: { color: C.INK } });
    slide.addText(String(o.badge), {
      x: W - MX - 0.62, y: tY + 0.03, w: 0.56, h: 0.56, fontSize: 14, bold: true,
      color: C.GOLDL, align: "center", valign: "middle", fontFace: F.B, margin: 0,
    });
  }
  if (o.sub) {
    slide.addText(o.sub, {
      x: MX, y: tY + 0.62, w: CW, h: 0.30, fontSize: 12.5, color: C.GREY, fontFace: F.B,
      valign: "middle", margin: 0,
    });
  }
}

// 底部「口播讲稿」卡：把原本放在备注栏的稿子搬到页面上
function noteCard(slide, text, top) {
  const y = top || NY;
  const w = CW, x = MX;
  const availH = H - 0.18 - y;
  // 在可用高度内尽量放大字号（长讲稿自然变小，短讲稿变大，减少留白）
  let pt = fillFont(text, w - 0.86, availH - 0.66, 9, 13.5);
  let ln = linesFor(text, w - 0.86, pt);
  let h = 0.38 + ln * (pt * 1.52 / 72) + 0.26;
  if (h > availH) h = availH;
  slide.addShape("roundRect", {
    x, y, w, h, rectRadius: 0.06, fill: { color: C.ICE2 }, line: { color: C.LINE, width: 0.75 },
  });
  slide.addShape("ellipse", { x: x + 0.22, y: y + 0.14, w: 0.11, h: 0.11, fill: { color: C.GOLD } });
  slide.addText("口播讲稿", {
    x: x + 0.40, y: y + 0.06, w: 2.2, h: 0.26, fontSize: 10.5, bold: true, color: C.STEEL,
    fontFace: F.B, valign: "middle", margin: 0,
  });
  slide.addText(text, {
    x: x + 0.30, y: y + 0.34, w: w - 0.62, h: h - 0.40, fontSize: pt, color: "33475E",
    fontFace: F.B, valign: "top", margin: 0, lineSpacing: pt * 1.34,
  });
  return h;
}

function footer(slide, n) {
  slide.addText(String(n), {
    x: W - MX - 0.6, y: H - 0.42, w: 0.6, h: 0.28, fontSize: 9.5, color: C.GREY,
    align: "right", fontFace: F.B, valign: "middle", margin: 0,
  });
}

// 圆角卡片：标题 + 正文，正文自动适配字号
function card(slide, o) {
  const { x, y, w, h, fill, line, title, body, tSize, dot, tColor, bodyMax } = o;
  slide.addShape("roundRect", {
    x, y, w, h, rectRadius: 0.07,
    fill: { color: fill || C.ICE }, line: { color: line || C.LINE, width: 0.75 },
  });
  let cy = y + 0.16;
  if (dot !== undefined) {
    slide.addShape("ellipse", { x: x + 0.20, y: y + 0.20, w: 0.30, h: 0.30, fill: { color: C.INK } });
    slide.addText(String(dot), {
      x: x + 0.20, y: y + 0.20, w: 0.30, h: 0.30, fontSize: 11, bold: true, color: C.WHITE,
      align: "center", valign: "middle", fontFace: F.B, margin: 0,
    });
  }
  if (title) {
    const tx = dot !== undefined ? x + 0.58 : x + 0.22;
    const tw = w - (tx - x) - 0.22;
    const tp = fillFont(title, tw, 0.52, 11.5, tSize || 16);
    slide.addText(title, {
      x: tx, y: y + 0.14, w: tw, h: 0.54, fontSize: tp, bold: true, color: tColor || C.INK,
      fontFace: F.H, valign: "middle", margin: 0,
    });
    cy = y + 0.72;
  }
  if (body) {
    const bx = x + 0.24, bw = w - 0.48, bh = h - (cy - y) - 0.16;
    const bp = fillFont(body, bw, bh, 9, bodyMax || 15);
    slide.addText(body, {
      x: bx, y: cy, w: bw, h: bh, fontSize: bp, color: C.TEXT, fontFace: F.B,
      valign: "top", margin: 0, lineSpacing: bp * 1.38,
    });
  }
}

// ---------------------------------------------------------------- 版式：封面
function slideCover(pres, o) {
  const s = pres.addSlide();
  s.background = { color: C.INK };
  s.addShape("rect", { x: 0, y: 0, w: W, h: H, fill: { color: C.INK } });
  // 右下角装饰：同心圆（不是条纹）
  s.addShape("ellipse", { x: W - 3.4, y: H - 3.4, w: 5.2, h: 5.2, fill: { color: "16365C" } });
  s.addShape("ellipse", { x: W - 2.6, y: H - 2.6, w: 3.6, h: 3.6, fill: { color: "1B4F72" } });
  s.addShape("ellipse", { x: W - 1.9, y: H - 1.9, w: 2.2, h: 2.2, fill: { color: C.GOLD, transparency: 82 } });

  s.addText("项目答辩 · 数据治理方向", {
    x: 1.0, y: 1.15, w: 8.4, h: 0.34, fontSize: 13, color: C.GOLDL, bold: true,
    fontFace: F.B, charSpacing: 2, valign: "middle", margin: 0,
  });
  s.addText(o.title, {
    x: 1.0, y: 1.72, w: 9.2, h: 1.5, fontSize: 44, bold: true, color: C.WHITE,
    fontFace: F.H, valign: "top", margin: 0, lineSpacing: 58,
  });
  s.addShape("ellipse", { x: 1.02, y: 3.34, w: 0.14, h: 0.14, fill: { color: C.GOLD } });
  s.addText(o.subtitle, {
    x: 1.0, y: 3.62, w: 8.6, h: 0.72, fontSize: 17, color: "CFDCEC", fontFace: F.B,
    valign: "top", margin: 0, lineSpacing: 26,
  });
  // 底部信息条
  s.addShape("roundRect", { x: 1.0, y: 4.62, w: 9.0, h: 1.05, rectRadius: 0.05, fill: { color: "173A61" }, line: { color: "28507C", width: 0.75 } });
  s.addText(o.meta, {
    x: 1.24, y: 4.62, w: 8.6, h: 1.05, fontSize: 12.5, color: "C8D8EA", fontFace: F.B,
    valign: "middle", margin: 0, lineSpacing: 21,
  });
  s.addText(o.stats, {
    x: 1.0, y: 6.05, w: 9.0, h: 0.5, fontSize: 13, color: C.GOLDL, bold: true, fontFace: F.B,
    valign: "middle", margin: 0,
  });
  s.addText(o.speech, {
    x: 1.0, y: 6.55, w: 11.3, h: 0.8, fontSize: 10.5, color: "93A9C2", fontFace: F.B,
    valign: "top", margin: 0, lineSpacing: 16,
  });
  if (o.notes) s.addNotes(o.notes);
  return s;
}

// ---------------------------------------------------------------- 版式：章节隔页
function slideSection(pres, o) {
  const s = pres.addSlide();
  s.background = { color: C.INK };
  s.addShape("rect", { x: 0, y: 0, w: 8.6, h: H, fill: { color: "123253" } });
  s.addShape("ellipse", { x: 9.6, y: -1.6, w: 5.4, h: 5.4, fill: { color: C.GOLD, transparency: 88 } });
  s.addShape("ellipse", { x: 10.6, y: 3.4, w: 3.6, h: 3.6, fill: { color: "1B4F72" } });

  s.addText(o.no, {
    x: 1.1, y: 1.55, w: 3.0, h: 1.5, fontSize: 76, bold: true, color: C.GOLD,
    fontFace: F.H, valign: "middle", margin: 0,
  });
  s.addText(o.name, {
    x: 1.1, y: 3.05, w: 7.2, h: 0.8, fontSize: 30, bold: true, color: C.WHITE,
    fontFace: F.H, valign: "middle", margin: 0,
  });
  s.addText(o.desc, {
    x: 1.1, y: 3.95, w: 7.0, h: 1.1, fontSize: 13.5, color: "B9CBE0", fontFace: F.B,
    valign: "top", margin: 0, lineSpacing: 22,
  });
  // 该部分页码区间
  s.addText(o.range, {
    x: 1.1, y: 6.18, w: 6.6, h: 0.72, fontSize: 11, color: "7F97B3", fontFace: F.B,
    valign: "top", margin: 0, lineSpacing: 16,
  });
  s.addText(o.speech, {
    x: 1.1, y: 5.35, w: 7.2, h: 0.95, fontSize: 11, color: "8FA6C0", fontFace: F.B,
    valign: "top", margin: 0, lineSpacing: 17, italic: true,
  });
  if (o.notes) s.addNotes(o.notes);
  return s;
}

module.exports = {
  P, C, F, W, H, MX, CW, TY, SY, CY, CB, NY,
  textWidthIn, linesFor, fitFont, fillFont, needH, pageBase, noteCard, footer, card,
  slideCover, slideSection,
};
