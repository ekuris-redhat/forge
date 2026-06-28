// Modular, interactive Success Feedback and Social Sharing Component
export class WaitlistSuccess {
  constructor(container, data = {}, formInstance = null) {
    if (!container) {
      throw new Error("WaitlistSuccess requires a valid container element");
    }
    this.container = container;
    this.data = data;
    this.id = data.id || "N/A";
    this.email = data.business_email || "";
    this.formInstance = formInstance;

    this.init();
  }

  init() {
    this.render();
    this.setupListeners();
  }

  getReferralUrl() {
    const origin =
      window.location &&
      window.location.origin &&
      window.location.origin !== "null"
        ? window.location.origin
        : "https://forge-sdlc.com";
    return `${origin}/?ref=${this.id}`;
  }

  getTwitterShareUrl() {
    const text = `I just joined the waitlist for Forge, the autonomous AI software engineer! Secure your spot now to build and deploy 10x faster. 🚀 #ForgeSDLC`;
    const url = this.getReferralUrl();
    return `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`;
  }

  getLinkedInShareUrl() {
    const url = this.getReferralUrl();
    return `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`;
  }

  render() {
    // Overwrite the container contents with the interactive success card
    this.container.innerHTML = `
      <div class="success-icon">🎉</div>
      <h3 class="success-title">You're on the list!</h3>
      
      <p class="success-desc">
        Thank you for your interest. We will review your application and reach out to
        <strong id="submitted-email" class="text-indigo"></strong> shortly.
      </p>

      <div class="waitlist-status-card">
        <span class="waitlist-label">Your Waitlist Position</span>
        <div class="waitlist-number" id="waitlist-position">#${this.id}</div>
        <div class="waitlist-ref">
          Reference ID: <span id="waitlist-ref-id">${this.id}</span>
        </div>
      </div>

      <div class="sharing-section">
        <p class="share-prompt">Share with your network to move up in line!</p>
        <div class="share-buttons">
          <a href="${this.getTwitterShareUrl()}" target="_blank" rel="noopener noreferrer" class="btn btn-share btn-twitter" id="share-twitter" aria-label="Share on Twitter">
            <span class="share-icon">𝕏</span> Twitter / X
          </a>
          <a href="${this.getLinkedInShareUrl()}" target="_blank" rel="noopener noreferrer" class="btn btn-share btn-linkedin" id="share-linkedin" aria-label="Share on LinkedIn">
            <span class="share-icon">💼</span> LinkedIn
          </a>
        </div>
        
        <div class="copy-link-wrapper">
          <button class="btn btn-secondary btn-copy" id="btn-copy-link" aria-label="Copy your referral link">
            <span class="copy-icon">🔗</span> Copy Waitlist Link
          </button>
          <div class="copy-toast" id="copy-toast" role="status" aria-live="polite" style="display: none; opacity: 0;">
            Link copied to clipboard!
          </div>
        </div>
      </div>

      <button class="btn btn-secondary mt-8 btn-reset" id="btn-reset-form">
        Register another email
      </button>
    `;

    // Explicitly set textContent and innerText for complete JSDOM compatibility
    const submittedEmail =
      document.getElementById("submitted-email") ||
      this.container.querySelector("#submitted-email");
    if (submittedEmail) {
      submittedEmail.textContent = this.email;
      submittedEmail.innerText = this.email;
    }
  }

  setupListeners() {
    const copyBtn = this.container.querySelector(".btn-copy");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => this.handleCopy());
    }

    const resetBtn = this.container.querySelector(".btn-reset");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        if (
          this.formInstance &&
          typeof this.formInstance.resetForm === "function"
        ) {
          this.formInstance.resetForm();
        }
      });
    }
  }

  async handleCopy() {
    const referralUrl = this.getReferralUrl();
    const nav =
      typeof window !== "undefined" && window.navigator
        ? window.navigator
        : typeof navigator !== "undefined"
          ? navigator
          : null;
    try {
      if (nav && nav.clipboard && nav.clipboard.writeText) {
        await nav.clipboard.writeText(referralUrl);
      } else {
        // Fallback copy logic
        const textarea = document.createElement("textarea");
        textarea.value = referralUrl;
        textarea.style.position = "fixed"; // Prevent scrolling to bottom of page
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
      }
      this.showToast();
    } catch (err) {
      console.error("Failed to copy link: ", err);
    }
  }

  showToast() {
    const toast = this.container.querySelector(".copy-toast");
    const copyBtn = this.container.querySelector(".btn-copy");

    if (copyBtn) {
      const originalText = copyBtn.innerHTML;
      copyBtn.innerHTML = '<span class="copy-icon">✓</span> Copied!';
      copyBtn.classList.add("copied");
      setTimeout(() => {
        copyBtn.innerHTML = originalText;
        copyBtn.classList.remove("copied");
      }, 2000);
    }

    if (toast) {
      toast.style.display = "block";
      // Force redraw
      toast.offsetHeight;
      toast.style.opacity = "1";
      toast.style.transition = "opacity 0.3s ease";

      if (this.toastTimeout) {
        clearTimeout(this.toastTimeout);
      }

      this.toastTimeout = setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => {
          toast.style.display = "none";
        }, 3000);
      }, 2000);
    }
  }
}
