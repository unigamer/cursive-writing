// Glue for the single-file page made by `python tools/build_web.py --standalone`.
// Not used by the served page (index.html).
//
// The build inlines, as non-executing script elements:
//   #cursive-styles  JSON: the style list (data/index.json)
//   #cursive-engine  JavaScript: the style data plus the engine and worker.js,
//                    bundled into one classic script
// This runs the engine in a Worker made from a blob, so the page also works
// when opened straight from disk. If the browser refuses that worker, it runs
// the same code on the page instead (a little less smooth while typing).

(() => {
  const engineSource = document.getElementById("cursive-engine").textContent;
  const styles = JSON.parse(document.getElementById("cursive-styles").textContent).styles;

  // Runs the worker code on the page, with a stand-in for the worker's `self`.
  function inPageEngine(port) {
    const self = {
      postMessage: (data) => setTimeout(() => port.onmessage?.({ data })),
      onmessage: null,
    };
    new Function("self", engineSource)(self);
    return { postMessage: (data) => setTimeout(() => self.onmessage({ data })) };
  }

  // Looks like a Worker to app.js: postMessage, onmessage, onerror.
  function worker() {
    const port = { onmessage: null, onerror: null, postMessage: (m) => queue.push(m) };
    const queue = []; // messages sent before we know which engine runs
    let engine = null;
    let answered = false;

    const useEngine = (e) => {
      engine = e;
      port.postMessage = (m) => engine.postMessage(m);
      for (const m of queue.splice(0)) engine.postMessage(m);
    };
    const fallBack = () => {
      if (engine?.inPage) return;
      try {
        engine?.terminate?.();
        const e = inPageEngine(port);
        e.inPage = true;
        useEngine(e);
      } catch (err) {
        port.onerror?.({ message: String(err?.message ?? err) });
      }
    };

    try {
      const url = URL.createObjectURL(new Blob([engineSource], { type: "text/javascript" }));
      const w = new Worker(url);
      const sent = [];
      w.onmessage = (e) => {
        answered = true;
        port.onmessage?.(e);
      };
      w.onerror = (e) => {
        e.preventDefault?.();
        if (answered) port.onerror?.(e);
        else {
          // the worker never started: replay everything on the page
          queue.unshift(...sent);
          fallBack();
        }
      };
      engine = { postMessage: (m) => (answered || sent.push(m), w.postMessage(m)), terminate: () => w.terminate() };
      useEngine(engine);
    } catch {
      fallBack();
    }
    return port;
  }

  window.CURSIVE_STANDALONE = { styles, worker };
})();
