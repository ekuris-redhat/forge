/* Custom JavaScript for Forge SDLC Documentation Portal */

document.addEventListener("DOMContentLoaded", () => {
  console.log("Zensical Documentation Portal successfully initialized.");

  // Progressive enhancement: add keyboard shortcut helper for search
  const searchInput = document.querySelector(".md-search__input");
  if (searchInput) {
    document.addEventListener("keydown", (e) => {
      // Focus search input when pressing '/' key outside text fields
      if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
        e.preventDefault();
        searchInput.focus();
      }
    });
  }
});
