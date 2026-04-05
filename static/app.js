const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');

const imageInput = document.getElementById('imageInput');
const pickModeBtn = document.getElementById('pickModeBtn');
const runBtn = document.getElementById('runBtn');
const clearBtn = document.getElementById('clearBtn');

const colorTolerance = document.getElementById('colorTolerance');
const stepPx = document.getElementById('stepPx');
const minScore = document.getElementById('minScore');

const colorToleranceVal = document.getElementById('colorToleranceVal');
const stepPxVal = document.getElementById('stepPxVal');
const minScoreVal = document.getElementById('minScoreVal');

const chip = document.getElementById('pickedColorChip');
const statusNode = document.getElementById('status');

let img = new Image();
let imageLoaded = false;
let pickMode = false;
let pickedColor = null; // HSV
let pickedColorRgb = null;

let roi = null;
let dragging = false;
let dragStart = null;
let result = null;

const setStatus = (msg) => {
  statusNode.textContent = msg;
};

const rgbToHsv = (r, g, b) => {
  r /= 255;
  g /= 255;
  b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const d = max - min;
  let h = 0;
  const s = max === 0 ? 0 : d / max;
  const v = max;

  if (d !== 0) {
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)); break;
      case g: h = ((b - r) / d + 2); break;
      case b: h = ((r - g) / d + 4); break;
    }
    h /= 6;
  }

  return [Math.round(h * 179), Math.round(s * 255), Math.round(v * 255)];
};

const redraw = () => {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (imageLoaded) {
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  }

  if (result?.boxes?.length) {
    ctx.lineWidth = 1.5;
    for (const b of result.boxes) {
      const alpha = Math.max(0.15, Math.min(0.9, b.score));
      ctx.strokeStyle = `rgba(61, 231, 120, ${alpha})`;
      ctx.strokeRect(b.x, b.y, b.w, b.h);
    }

    ctx.strokeStyle = '#ffce3a';
    ctx.lineWidth = 2;
    ctx.beginPath();
    result.centers.forEach((p, i) => {
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.stroke();
  }

  if (roi) {
    ctx.strokeStyle = '#35b7ff';
    ctx.lineWidth = 2;
    ctx.strokeRect(roi.x, roi.y, roi.w, roi.h);
    ctx.fillStyle = 'rgba(53, 183, 255, 0.15)';
    ctx.fillRect(roi.x, roi.y, roi.w, roi.h);
  }
};

const getMousePos = (event) => {
  const rect = canvas.getBoundingClientRect();
  const sx = canvas.width / rect.width;
  const sy = canvas.height / rect.height;
  return {
    x: Math.round((event.clientX - rect.left) * sx),
    y: Math.round((event.clientY - rect.top) * sy),
  };
};

imageInput.addEventListener('change', (e) => {
  const file = e.target.files?.[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = () => {
    img.onload = () => {
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      imageLoaded = true;
      roi = null;
      result = null;
      redraw();
      setStatus('Изображение загружено. Шаг 1: выберите цвет. Шаг 2: выделите ROI мышью.');
    };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
});

pickModeBtn.addEventListener('click', () => {
  pickMode = !pickMode;
  pickModeBtn.textContent = pickMode ? 'Режим пипетки: ON' : '1) Пикнуть цвет';
  setStatus(pickMode ? 'Кликните по изображению, чтобы выбрать цвет стены.' : 'Режим пипетки выключен.');
});

clearBtn.addEventListener('click', () => {
  roi = null;
  result = null;
  redraw();
  setStatus('Сброс выполнен. Выберите ROI заново.');
});

canvas.addEventListener('mousedown', (e) => {
  if (!imageLoaded || pickMode) return;
  dragging = true;
  dragStart = getMousePos(e);
  roi = { x: dragStart.x, y: dragStart.y, w: 1, h: 1 };
  redraw();
});

canvas.addEventListener('mousemove', (e) => {
  if (!dragging || !dragStart) return;
  const p = getMousePos(e);
  roi = {
    x: Math.min(dragStart.x, p.x),
    y: Math.min(dragStart.y, p.y),
    w: Math.max(2, Math.abs(p.x - dragStart.x)),
    h: Math.max(2, Math.abs(p.y - dragStart.y)),
  };
  redraw();
});

canvas.addEventListener('mouseup', () => {
  dragging = false;
  if (roi) {
    setStatus(`ROI выбран: x=${roi.x}, y=${roi.y}, w=${roi.w}, h=${roi.h}`);
  }
});

canvas.addEventListener('click', (e) => {
  if (!pickMode || !imageLoaded) return;
  const p = getMousePos(e);
  const px = ctx.getImageData(p.x, p.y, 1, 1).data;
  pickedColorRgb = [px[0], px[1], px[2]];
  pickedColor = rgbToHsv(px[0], px[1], px[2]);
  chip.textContent = `HSV ${pickedColor.join(',')}`;
  chip.style.background = `rgb(${px[0]},${px[1]},${px[2]})`;
  chip.style.color = px[0] + px[1] + px[2] > 400 ? '#000' : '#fff';
  pickMode = false;
  pickModeBtn.textContent = '1) Пикнуть цвет';
  setStatus(`Цвет выбран. RGB=${pickedColorRgb.join(', ')} HSV=${pickedColor.join(', ')}`);
});

[colorTolerance, stepPx, minScore].forEach((input) => {
  input.addEventListener('input', () => {
    colorToleranceVal.textContent = colorTolerance.value;
    stepPxVal.textContent = stepPx.value;
    minScoreVal.textContent = minScore.value;
  });
});

runBtn.addEventListener('click', async () => {
  if (!imageLoaded) {
    setStatus('Сначала загрузите изображение.');
    return;
  }
  if (!pickedColor) {
    setStatus('Сначала выберите цвет стены.');
    return;
  }
  if (!roi || roi.w < 2 || roi.h < 2) {
    setStatus('Сначала выделите ROI.');
    return;
  }

  setStatus('Выполняю двунаправленное следование...');

  try {
    const payload = {
      imageData: canvas.toDataURL('image/png'),
      roi,
      pickedColor,
      colorTolerance: Number(colorTolerance.value),
      stepPx: Number(stepPx.value),
      minScore: Number(minScore.value),
    };

    const resp = await fetch('/api/follow', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const data = await resp.json();
    if (!resp.ok) {
      setStatus(`Ошибка: ${data.error || 'unknown'}`);
      return;
    }

    result = data;
    redraw();

    setStatus([
      `Готово. Точек траектории: ${data.stats.count}`,
      `Forward: ${data.stats.forward}, Backward: ${data.stats.backward}`,
      `Тип траектории: ${data.trajectoryType}`,
      `Оценка толщины шаблона: ${data.templateThickness.toFixed(3)}`,
      `Параметры: step=${data.stats.stepPx}, tol=${data.stats.colorTolerance}, minScore=${data.stats.minScore}`,
    ].join('\n'));
  } catch (err) {
    setStatus(`Сетевая/серверная ошибка: ${err.message}`);
  }
});

setStatus('Загрузите изображение и начните с выбора цвета стены.');
