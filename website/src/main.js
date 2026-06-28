// Forge Marketing Website JavaScript Entrypoint
document.addEventListener("DOMContentLoaded", () => {
  console.log("Forge Marketing Website initialized successfully!");

  // Sticky header scroll detection
  const header = document.getElementById("site-header");
  if (header) {
    const handleScroll = () => {
      if (window.scrollY > 20) {
        header.classList.add("scrolled");
      } else {
        header.classList.remove("scrolled");
      }
    };

    // Initialize state on load
    handleScroll();
    window.addEventListener("scroll", handleScroll);
  }

  // Mobile Drawer Toggle
  const navToggle = document.getElementById("nav-toggle");
  const drawerClose = document.getElementById("drawer-close");
  const mobileDrawer = document.getElementById("mobile-drawer");
  const drawerBackdrop = document.getElementById("drawer-backdrop");

  const openDrawer = () => {
    if (!mobileDrawer) return;
    mobileDrawer.classList.add("is-open");
    mobileDrawer.setAttribute("aria-hidden", "false");

    if (drawerBackdrop) {
      drawerBackdrop.classList.add("is-active");
      drawerBackdrop.setAttribute("aria-hidden", "false");
    }

    if (navToggle) {
      navToggle.setAttribute("aria-expanded", "true");
      navToggle.setAttribute("aria-label", "Close menu");
    }

    document.body.style.overflow = "hidden";

    // Accessibility: Focus close button inside drawer when opened
    if (drawerClose) {
      drawerClose.focus();
    }
  };

  const closeDrawer = () => {
    if (!mobileDrawer) return;
    mobileDrawer.classList.remove("is-open");
    mobileDrawer.setAttribute("aria-hidden", "true");

    if (drawerBackdrop) {
      drawerBackdrop.classList.remove("is-active");
      drawerBackdrop.setAttribute("aria-hidden", "true");
    }

    if (navToggle) {
      navToggle.setAttribute("aria-expanded", "false");
      navToggle.setAttribute("aria-label", "Open menu");
      // Accessibility: return focus to hamburger button
      navToggle.focus();
    }

    document.body.style.overflow = "";
  };

  if (navToggle) {
    navToggle.addEventListener("click", () => {
      const isExpanded = navToggle.getAttribute("aria-expanded") === "true";
      if (isExpanded) {
        closeDrawer();
      } else {
        openDrawer();
      }
    });

    // Support Space & Enter keys for full keyboard accessibility
    navToggle.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        const isExpanded = navToggle.getAttribute("aria-expanded") === "true";
        if (isExpanded) {
          closeDrawer();
        } else {
          openDrawer();
        }
      }
    });
  }

  if (drawerClose) {
    drawerClose.addEventListener("click", closeDrawer);
    drawerClose.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        closeDrawer();
      }
    });
  }

  if (drawerBackdrop) {
    drawerBackdrop.addEventListener("click", closeDrawer);
  }

  // Close drawer on Escape key press
  document.addEventListener("keydown", (e) => {
    if (
      e.key === "Escape" &&
      mobileDrawer &&
      mobileDrawer.classList.contains("is-open")
    ) {
      closeDrawer();
    }
  });

  // Setup smooth scrolling for navigation links
  const links = document.querySelectorAll(
    ".nav-link, .drawer-nav-link, .hero-actions a, .footer-link, .drawer-btn",
  );
  links.forEach((link) => {
    link.addEventListener("click", (e) => {
      const href = link.getAttribute("href");

      const wasDrawerOpen =
        mobileDrawer && mobileDrawer.classList.contains("is-open");
      if (wasDrawerOpen) {
        closeDrawer();
      }

      if (href && href.startsWith("#") && href.length > 1) {
        e.preventDefault();
        const targetElement = document.querySelector(href);
        if (targetElement) {
          // If drawer was open, delay scroll slightly to allow layout calculations to adjust
          const delay = wasDrawerOpen ? 50 : 0;
          setTimeout(() => {
            targetElement.scrollIntoView({
              behavior: "smooth",
              block: "start",
            });
          }, delay);
        }
      }
    });
  });
});
