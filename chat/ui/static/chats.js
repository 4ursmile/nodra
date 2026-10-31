// Download a chat as a file, and import one: from a file (.nodrachat.json, .html or .zip) or pasted text.
import { html, useState } from "./vendor/preact-htm.js";
import { Ic } from "./icons.js";
import { ask, toast, Modal, Seg, saveFile, fileB64 } from "./ui.js";

// One dialog for the three downloads. -> the saved file name, or null.
export async function sendChat({ id }) {
  const v = await ask({ title: "Download this chat", text: "Whoever imports the file gets a new chat that knows the conversation.", submit: "Download", fields: [
    { name: "how", label: "Format", type: "select", value: "json", options: [{ value: "json", label: "Chat file (.nodrachat.json)" }, { value: "html", label: "Web page (.html, readable; can be imported too)" }, { value: "zip", label: "Zip (chat.html, chat.nodrachat.json and files/)" }] },
    { name: "files", label: "Working folder files", type: "select", value: "0", options: [{ value: "0", label: "Conversation only" }, { value: "1", label: "Include the folder's files (size capped)" }] }] });
  if (!v) return null;
  const name = await saveFile("sessions/export?id=" + encodeURIComponent(id) + "&format=" + v.how + "&files=" + v.files);
  toast("Saved " + name);
  return name;
}

// Two ways in: a file (picked or dropped) or pasted text (the exported .json, or the .html page source).
export function ImportDialog({ post, close, done, extra }) {
  const [tab, setTab] = useState("file"), [text, setText] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState(""), [over, setOver] = useState(false), [fname, setFname] = useState("");
  const go = async (body) => {
    setBusy(true); setErr("");
    try { const r = await post("sessions/import", { ...body, extra }); toast("Imported " + r.messages + " messages" + (r.files ? " and " + r.files + " files" : "")); done(r.session); }
    catch (e) { setErr(e.message); setBusy(false); }
  };
  const file = async (f) => {
    if (!f) return; setFname(f.name);
    if (f.size > 40 * 1024 * 1024) return setErr("That file is over 40 MB.");
    try { go({ b64: await fileB64(f), name: f.name }); } catch (e) { setErr(e.message); }
  };
  const drop = (e) => { e.preventDefault(); setOver(false); file(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]); };
  return html`<${Modal} close=${close} wide=${true}><h1>Import a chat</h1><p class="sub">Makes a NEW chat from an exported one. Nothing in it is run; the conversation is only read.</p>
    <${Seg} items=${[{ id: "file", label: "Upload a file", icon: "upload" }, { id: "text", label: "Paste text", icon: "note" }]} value=${tab} onChange=${(t) => { setTab(t); setErr(""); }}/>
    <div style="margin-top:14px">
      ${tab === "text" && html`<div class="field"><label>The exported chat: .nodrachat.json content or the .html page source</label><textarea rows="9" autofocus value=${text} onInput=${(e) => setText(e.target.value)} placeholder='{"format": "nodra-chat", ...}' style="width:100%;font:12px var(--mono)"></textarea></div>
        <div class="row"><span class="mute small grow">${text ? Math.round(text.length / 1024) + " KB" : ""}</span><button class="btn acc" disabled=${busy || !text.trim()} onClick=${() => go({ text })}>${busy ? "Importing…" : "Import"}</button></div>`}
      ${tab === "file" && html`<label class=${"imp-drop" + (over ? " over" : "")} onDragOver=${(e) => { e.preventDefault(); setOver(true); }} onDragLeave=${() => setOver(false)} onDrop=${drop}>
        ${Ic("upload", 22)}<b>${busy ? "Importing " + fname + "…" : fname || "Drop a file here or click to choose"}</b><span class="mute small">An .nodrachat.json, .html page or .zip, up to 40 MB</span>
        <input type="file" accept=".json,.html,.htm,.zip,application/json,text/html,application/zip" onChange=${(e) => file(e.target.files && e.target.files[0])} disabled=${busy} hidden/></label>`}
    </div>
    ${err && html`<p class="err" role="alert" style="color:var(--bad,#c0392b);margin-top:10px">${err}</p>`}
    <div class="row" style="margin-top:14px"><span class="grow"></span><button class="btn" onClick=${close}>Close</button></div><//>`;
}
