async function(args) {
  const options =
      [...document.querySelectorAll('[role="listbox"] [role="option"]')];
  return [...new Set(
      options.filter(el => el.checkVisibility({visibilityProperty: true}))
          .map(el => (el.getAttribute('aria-label') || el.innerText).trim())
          .filter(Boolean))];
}
