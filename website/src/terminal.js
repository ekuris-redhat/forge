// Reusable, responsive Terminal Simulator Component
export const DEFAULT_LOGS = [
  { type: "log-info", text: "[INFO] Redis Streams consumer connected" },
  { type: "log-info", text: "[INFO] Queue worker active. Listening on stream: forge:events" },
  { type: "log-info", text: "[INFO] Received ticket: AISOS-1965 (Develop responsive section grids)" },
  { type: "log-info", text: "[INFO] Planning task: Develop responsive section grids..." },
  { type: "log-success", text: "[SUCCESS] Task plan generated successfully" },
  { type: "log-text", text: "[INFO] Spawning container sandbox (forge-AISOS-1965-sandbox)..." },
  { type: "log-text", text: "[INFO] Modifying index.html and main.css..." },
  { type: "log-text", text: "[INFO] Running validation tests (npm run test)..." },
  { type: "log-success", text: "[SUCCESS] All unit tests passed cleanly!" },
  { type: "log-success", text: "[SUCCESS] Task complete. Pull request #14 opened successfully! 🚀" }
];

export class TerminalSimulator {
  constructor(options = {}) {
    this.logs = options.logs || DEFAULT_LOGS;
    this.container = options.container || null;
    if (typeof options.container === "string") {
      this.container = document.querySelector(options.container);
    }

    // Configurable delay range in ms
    this.minDelay = options.minDelay !== undefined ? options.minDelay : 800;
    this.maxDelay = options.maxDelay !== undefined ? options.maxDelay : 1200;

    // Callbacks
    this.onLogPrinted = options.onLogPrinted || null;
    this.onComplete = options.onComplete || null;
    this.onStateChange = options.onStateChange || null;

    // Simulation State
    this.currentLogIndex = 0;
    this.timer = null;
    this.isPausedState = false;
    this.isCompletedState = false;
    this.controlsLayout = options.controlsLayout || "within"; // 'within' (inside chrome) or 'beneath' (outside chrome)

    // Element references
    this.terminalWindow = null;
    this.terminalBody = null;
    this.terminalOutput = null;
    this.pauseBtn = null;
    this.restartBtn = null;
    this.resetBtn = null;
    this.triggerBtn = null;

    // Init UI and bind events
    this.init(options);
  }

  init(options) {
    if (this.container) {
      this.render();
    }

    // Resolve element references, checking container first then globally
    const findEl = (selector, fallbackId) => {
      if (selector) {
        return this.container ? this.container.querySelector(selector) : document.querySelector(selector);
      }
      return this.container ? this.container.querySelector(`#${fallbackId}`) : document.getElementById(fallbackId);
    };

    this.terminalWindow = this.container ? this.container.querySelector(".terminal-window") : document.querySelector(".terminal-window");
    this.terminalBody = findEl(options.terminalBodySelector, "terminal-body");
    this.terminalOutput = findEl(options.terminalOutputSelector, "terminal-output");
    this.pauseBtn = findEl(options.pauseBtnSelector, "terminal-pause");
    this.restartBtn = findEl(options.restartBtnSelector, "terminal-restart");
    this.resetBtn = findEl(options.resetBtnSelector, "terminal-reset");
    this.triggerBtn = findEl(options.triggerBtnSelector, "btn-trigger-simulation");

    this.bindEvents();

    if (options.autoStart !== false) {
      this.start();
    }
  }

  render() {
    // Dynamically render a clean, responsive terminal markup into container if it is empty
    if (this.container && this.container.innerHTML.trim() === "") {
      const showWithin = this.controlsLayout === "within" || this.controlsLayout === "inside";
      const showBeneath = this.controlsLayout === "beneath" || this.controlsLayout === "outside";

      let html = `
        <div class="terminal-window" style="width: 100%;">
          <div class="terminal-header">
            <div class="terminal-dots">
              <span class="dot red"></span>
              <span class="dot yellow"></span>
              <span class="dot green"></span>
            </div>
            <span class="terminal-title">forge@sandbox:~/.forge</span>
            <div class="terminal-action-icons">
              <span class="icon-refresh" id="terminal-reset" title="Restart Simulation">🔄</span>
            </div>
          </div>
          <div class="terminal-body" id="terminal-body">
            <div class="terminal-line"><span class="prompt-symbol">$</span> <span class="typed-command">forge worker start</span></div>
            <div class="terminal-output typing" id="terminal-output"></div>
          </div>
      `;

      if (showWithin) {
        html += `
          <div class="terminal-controls">
            <button class="terminal-btn btn-pause" id="terminal-pause" aria-label="Pause Simulation">
              <span class="btn-icon">⏸️</span> <span class="btn-text">Pause</span>
            </button>
            <button class="terminal-btn btn-restart" id="terminal-restart" aria-label="Restart Simulation">
              <span class="btn-icon">🔄</span> <span class="btn-text">Restart</span>
            </button>
          </div>
        `;
      }

      html += `</div>`; // Close terminal-window

      if (showBeneath) {
        html += `
          <div class="terminal-controls external">
            <button class="terminal-btn btn-pause" id="terminal-pause" aria-label="Pause Simulation">
              <span class="btn-icon">⏸️</span> <span class="btn-text">Pause</span>
            </button>
            <button class="terminal-btn btn-restart" id="terminal-restart" aria-label="Restart Simulation">
              <span class="btn-icon">🔄</span> <span class="btn-text">Restart</span>
            </button>
          </div>
        `;
      }

      this.container.innerHTML = html;
    }
  }

  bindEvents() {
    this.togglePlayPause = this.togglePlayPause.bind(this);
    this.restart = this.restart.bind(this);

    if (this.pauseBtn) {
      this.pauseBtn.addEventListener("click", this.togglePlayPause);
    }
    if (this.restartBtn) {
      this.restartBtn.addEventListener("click", this.restart);
    }
    if (this.resetBtn) {
      this.resetBtn.addEventListener("click", this.restart);
    }
    if (this.triggerBtn) {
      this.triggerBtn.addEventListener("click", this.restart);
    }
  }

  start() {
    this.currentLogIndex = 0;
    this.isPausedState = false;
    this.isCompletedState = false;

    if (this.terminalOutput) {
      this.terminalOutput.innerHTML = "";
    }

    if (this.terminalWindow) {
      this.terminalWindow.classList.remove("paused", "completed");
    }

    if (this.timer) {
      clearTimeout(this.timer);
    }

    this.updateControls();
    this.scheduleNextLog();
    this.triggerStateCallback();
  }

  restart() {
    this.start();
  }

  pause() {
    if (this.isPausedState || this.isCompletedState) return;

    this.isPausedState = true;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }

    if (this.terminalWindow) {
      this.terminalWindow.classList.add("paused");
    }

    this.updateControls();
    this.triggerStateCallback();
  }

  resume() {
    if (!this.isPausedState || this.isCompletedState) return;

    this.isPausedState = false;
    if (this.terminalWindow) {
      this.terminalWindow.classList.remove("paused");
    }

    this.updateControls();
    this.scheduleNextLog();
    this.triggerStateCallback();
  }

  togglePlayPause() {
    if (this.isPausedState) {
      this.resume();
    } else {
      this.pause();
    }
  }

  scheduleNextLog() {
    if (this.isPausedState || this.isCompletedState) return;

    const delay = this.minDelay + Math.random() * (this.maxDelay - this.minDelay);
    if (delay <= 0) {
      this.printNextLog();
    } else {
      this.timer = setTimeout(() => {
        this.printNextLog();
      }, delay);
    }
  }

  printNextLog() {
    if (this.isPausedState || this.isCompletedState) return;

    if (this.currentLogIndex < this.logs.length) {
      const log = this.logs[this.currentLogIndex];
      
      if (this.terminalOutput) {
        const logDiv = document.createElement("div");
        logDiv.className = log.type;
        logDiv.innerText = log.text;
        this.terminalOutput.appendChild(logDiv);
      }

      this.currentLogIndex++;

      // Auto scroll terminal to bottom
      if (this.terminalBody) {
        this.terminalBody.scrollTop = this.terminalBody.scrollHeight;
      }

      if (this.onLogPrinted) {
        this.onLogPrinted(log, this.currentLogIndex);
      }

      if (this.currentLogIndex === this.logs.length) {
        this.isCompletedState = true;
        if (this.terminalWindow) {
          this.terminalWindow.classList.add("completed");
        }
        this.updateControls();
        this.triggerStateCallback();
        if (this.onComplete) {
          this.onComplete();
        }
      } else {
        this.scheduleNextLog();
      }
    }
  }

  updateControls() {
    if (this.pauseBtn) {
      const btnText = this.pauseBtn.querySelector(".btn-text") || this.pauseBtn;
      const btnIcon = this.pauseBtn.querySelector(".btn-icon");

      if (this.isPausedState) {
        if (btnText === this.pauseBtn) {
          this.pauseBtn.innerText = "▶️ Resume";
        } else {
          btnText.innerText = "Resume";
          if (btnIcon) btnIcon.innerText = "▶️";
        }
        this.pauseBtn.setAttribute("aria-label", "Resume Simulation");
      } else {
        if (btnText === this.pauseBtn) {
          this.pauseBtn.innerText = "⏸️ Pause";
        } else {
          btnText.innerText = "Pause";
          if (btnIcon) btnIcon.innerText = "⏸️";
        }
        this.pauseBtn.setAttribute("aria-label", "Pause Simulation");
      }

      // Disable/style pause button if completed
      if (this.isCompletedState) {
        this.pauseBtn.setAttribute("disabled", "true");
        this.pauseBtn.classList.add("disabled");
      } else {
        this.pauseBtn.removeAttribute("disabled");
        this.pauseBtn.classList.remove("disabled");
      }
    }
  }

  triggerStateCallback() {
    if (this.onStateChange) {
      this.onStateChange({
        isPaused: this.isPausedState,
        isCompleted: this.isCompletedState,
        currentLogIndex: this.currentLogIndex,
        totalLogs: this.logs.length
      });
    }
  }

  get isPaused() {
    return this.isPausedState;
  }

  get isCompleted() {
    return this.isCompletedState;
  }

  get currentStep() {
    return this.currentLogIndex;
  }

  destroy() {
    if (this.timer) {
      clearTimeout(this.timer);
    }
    if (this.pauseBtn) {
      this.pauseBtn.removeEventListener("click", this.togglePlayPause);
    }
    if (this.restartBtn) {
      this.restartBtn.removeEventListener("click", this.restart);
    }
    if (this.resetBtn) {
      this.resetBtn.removeEventListener("click", this.restart);
    }
    if (this.triggerBtn) {
      this.triggerBtn.removeEventListener("click", this.restart);
    }
  }
}
