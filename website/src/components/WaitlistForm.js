// Modular, accessible Waitlist Form Component
export const BLOCKED_DOMAINS = new Set([
  "gmail.com",
  "yahoo.com",
  "hotmail.com",
  "outlook.com",
  "aol.com",
  "icloud.com",
  "mail.com",
  "zoho.com",
  "protonmail.com",
  "proton.me",
  "yandex.com",
  "gmx.com",
  "live.com",
]);

export class WaitlistForm {
  constructor(options = {}) {
    this.formId = options.formId || "waitlist-form";
    this.successId = options.successId || "form-success";
    this.resetBtnId = options.resetBtnId || "btn-reset-form";
    this.emailDisplayId = options.emailDisplayId || "submitted-email";

    this.form = document.getElementById(this.formId);
    this.successState = document.getElementById(this.successId);
    this.resetBtn = document.getElementById(this.resetBtnId);
    this.emailDisplay = document.getElementById(this.emailDisplayId);

    // Callbacks
    this.onSubmitSuccess = options.onSubmitSuccess || null;
    this.onSubmitError = options.onSubmitError || null;

    this.init();
  }

  init() {
    if (!this.form) return;

    this.form.addEventListener("submit", (e) => this.handleSubmit(e));

    // Live validation and error clearance on typing
    const inputs = this.form.querySelectorAll(".form-input");
    inputs.forEach((input) => {
      input.addEventListener("input", () => {
        this.clearFieldError(input);
      });
      input.addEventListener("change", () => {
        this.clearFieldError(input);
      });
    });

    if (this.resetBtn) {
      this.resetBtn.addEventListener("click", () => this.resetForm());
    }
  }

  validateEmail(email) {
    const re = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;
    return re.test(String(email).toLowerCase());
  }

  isCorporateEmail(email) {
    const parts = email.trim().toLowerCase().split("@");
    if (parts.length !== 2) return false;
    const domain = parts[1];

    // Check main domain and subdomains
    if (BLOCKED_DOMAINS.has(domain)) return false;
    for (const blocked of BLOCKED_DOMAINS) {
      if (domain.endsWith("." + blocked)) {
        return false;
      }
    }
    return true;
  }

  showFieldError(input, message) {
    const group = input.parentElement;
    if (group) {
      group.classList.add("has-error");
    }
    input.setAttribute("aria-invalid", "true");

    // Find or update error element
    const errorSpan = group ? group.querySelector(".error-msg") : null;
    if (errorSpan) {
      if (message) {
        errorSpan.textContent = message;
      }
      errorSpan.style.display = "block";
    }
  }

  clearFieldError(input) {
    const group = input.parentElement;
    if (group) {
      group.classList.remove("has-error");
    }
    input.setAttribute("aria-invalid", "false");

    const errorSpan = group ? group.querySelector(".error-msg") : null;
    if (errorSpan) {
      errorSpan.style.display = "none";
    }
  }

  handleSubmit(e) {
    e.preventDefault();

    let hasError = false;

    // Validate Name
    const nameInput = document.getElementById("user-name");
    if (nameInput) {
      if (!nameInput.value.trim()) {
        this.showFieldError(nameInput, "Please enter your name.");
        hasError = true;
      } else {
        this.clearFieldError(nameInput);
      }
    }

    // Validate Email
    const emailInput = document.getElementById("user-email");
    if (emailInput) {
      const emailValue = emailInput.value.trim();
      if (!emailValue) {
        this.showFieldError(emailInput, "Please enter your email address.");
        hasError = true;
      } else if (!this.validateEmail(emailValue)) {
        this.showFieldError(emailInput, "Please enter a valid email address.");
        hasError = true;
      } else if (!this.isCorporateEmail(emailValue)) {
        this.showFieldError(
          emailInput,
          "Personal email domains are not allowed. Please use a business email.",
        );
        hasError = true;
      } else {
        this.clearFieldError(emailInput);
      }
    }

    // Validate Company Size
    const companyInput = document.getElementById("user-company");
    if (companyInput) {
      if (!companyInput.value) {
        this.showFieldError(companyInput, "Please select your company size.");
        hasError = true;
      } else {
        this.clearFieldError(companyInput);
      }
    }

    // Validate Role
    const roleInput = document.getElementById("user-role");
    if (roleInput) {
      if (!roleInput.value) {
        this.showFieldError(roleInput, "Please select your primary role.");
        hasError = true;
      } else {
        this.clearFieldError(roleInput);
      }
    }

    if (!hasError) {
      const payload = {
        name: nameInput ? nameInput.value.trim() : "",
        business_email: emailInput ? emailInput.value.trim() : "",
        company_size: companyInput ? companyInput.value : "",
        role: roleInput ? roleInput.value : "",
      };

      this.handleSuccess(payload);
    } else {
      if (this.onSubmitError) {
        this.onSubmitError();
      }
    }
  }

  handleSuccess(payload) {
    if (this.emailDisplay && payload.business_email) {
      this.emailDisplay.innerText = payload.business_email;
      this.emailDisplay.textContent = payload.business_email;
    }

    if (this.form) {
      this.form.style.display = "none";
    }

    if (this.successState) {
      this.successState.style.display = "flex";
      this.successState.setAttribute("aria-hidden", "false");
    }

    if (this.onSubmitSuccess) {
      this.onSubmitSuccess(payload);
    }
  }

  resetForm() {
    if (this.form) {
      this.form.reset();
      this.form.style.display = "block";

      // Clear any remaining validation error states
      const inputs = this.form.querySelectorAll(".form-input");
      inputs.forEach((input) => {
        this.clearFieldError(input);
      });
    }

    if (this.successState) {
      this.successState.style.display = "none";
      this.successState.setAttribute("aria-hidden", "true");
    }
  }
}
