const SAMPLE_RATE = 16000;
const CHUNK_SIZE = 4096;
const MAX_VISIBLE_VERSES = 3;

let ws = null;
let audioContext = null;
let mediaStream = null;
let processor = null;
let isRecording = false;

let displayedVerses = [];
let totalChunks = 0;

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const versesEl = document.getElementById("verses");
const positionEl = document.getElementById("position");
const confidenceEl = document.getElementById("confidence");
const chunkCountEl = document.getElementById("chunk-count");
const meterEl = document.getElementById("meter");
const sesDbEl = document.getElementById("ses-db");

function verseKey(v) {
    return `${v.surah}:${v.ayah}`;
}

function addVerses(newVerses) {
    for (const v of newVerses) {
        const key = verseKey(v);
        const exists = displayedVerses.some(x => verseKey(x) === key);
        if (!exists) {
            displayedVerses.push(v);
        }
    }
    if (displayedVerses.length > MAX_VISIBLE_VERSES) {
        displayedVerses = displayedVerses.slice(-MAX_VISIBLE_VERSES);
    }
    renderVerses();
}

function renderVerses() {
    if (displayedVerses.length === 0) {
        versesEl.innerHTML = '<div class="placeholder">Mikrofona Kuran okunduğunda meal burada görünecek</div>';
        return;
    }

    const html = displayedVerses.map((v, idx) => {
        const isCurrent = idx === displayedVerses.length - 1;
        const cls = isCurrent ? "verse current" : "verse old";
        const nameTr = escapeHtml(v.surah_name_tr || `Sure ${v.surah}`);
        const nameAr = escapeHtml(v.surah_name_ar || "");
        return `
            <div class="${cls}">
                <div class="verse-header">
                    <div>
                        <span class="verse-name">${nameTr}</span>
                        ${nameAr ? `<span class="verse-name-ar">${nameAr}</span>` : ''}
                    </div>
                    <div class="verse-ref">${v.surah}:${v.ayah}</div>
                </div>
                <div class="verse-meal">${escapeHtml(v.meal) || '(meal bulunamadı)'}</div>
                <div class="verse-arabic">${escapeHtml(v.arabic)}</div>
            </div>
        `;
    }).join("");

    versesEl.innerHTML = html;
}

function escapeHtml(s) {
    if (!s) return "";
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function updateStatusBar(chunk) {
    totalChunks++;
    chunkCountEl.textContent = totalChunks;

    if (chunk.status === "matched" && chunk.verses && chunk.verses.length > 0) {
        const first = chunk.verses[0];
        const last = chunk.verses[chunk.verses.length - 1];
        const pos = chunk.verses.length === 1
            ? `${first.surah_name_tr} ${first.surah}:${first.ayah}`
            : `${first.surah_name_tr} ${first.surah}:${first.ayah}-${last.ayah}`;
        positionEl.textContent = pos;
        confidenceEl.textContent = chunk.confidence;
    }
}

async function startRecording() {
    try {
        displayedVerses = [];
        totalChunks = 0;
        renderVerses();

        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: SAMPLE_RATE,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
            }
        });

        audioContext = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: SAMPLE_RATE
        });

        const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
        ws = new WebSocket(`${wsProtocol}//${location.host}/audio`);
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
            isRecording = true;
            startBtn.disabled = true;
            stopBtn.disabled = false;
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "chunk") {
                    updateStatusBar(data);
                    if (data.status === "matched" && data.verses) {
                        addVerses(data.verses);
                    }
                }
            } catch (e) {
                console.error("Mesaj hatası:", e);
            }
        };

        ws.onerror = () => console.error("WebSocket hatası");
        ws.onclose = () => console.log("WebSocket kapandı");

        const source = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(CHUNK_SIZE, 1, 1);

        processor.onaudioprocess = (e) => {
            if (!isRecording || !ws || ws.readyState !== WebSocket.OPEN) return;

            const input = e.inputBuffer.getChannelData(0);

            let sum = 0;
            for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
            const rms = Math.sqrt(sum / input.length);
            const db = 20 * Math.log10(Math.max(rms, 1e-10));
            const normalized = Math.max(0, Math.min(100, (db + 60) * 1.67));
            meterEl.style.width = normalized + "%";
            sesDbEl.textContent = Math.round(db) + " dB";

            ws.send(input.buffer);
        };

        source.connect(processor);
        processor.connect(audioContext.destination);

    } catch (err) {
        console.error("HATA:", err);
        alert("Hata: " + err.message);
    }
}

function stopRecording() {
    isRecording = false;

    if (processor) { processor.disconnect(); processor = null; }
    if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
    if (audioContext) { audioContext.close(); audioContext = null; }

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "stop" }));
        setTimeout(() => { if (ws) ws.close(); ws = null; }, 500);
    }

    meterEl.style.width = "0%";
    startBtn.disabled = false;
    stopBtn.disabled = true;
}
