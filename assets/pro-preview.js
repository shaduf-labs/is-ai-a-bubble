(() => {
  const dialog = document.querySelector('[data-pro-access-dialog]')
  if (!(dialog instanceof HTMLDialogElement)) return
  let trigger = null
  for (const button of document.querySelectorAll('[data-pro-access]')) {
    button.addEventListener('click', () => {
      trigger = button
      if (!dialog.open) dialog.showModal()
    })
  }
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return
    const rect = dialog.getBoundingClientRect()
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close()
  })
  dialog.addEventListener('close', () => { trigger?.focus() })
})()
