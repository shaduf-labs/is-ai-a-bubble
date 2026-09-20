(() => {
  const form = document.querySelector('[data-pool-request-form]')
  if (!form) return
  const button = form.querySelector('button[type="submit"]')
  const status = form.querySelector('[data-request-status]')
  form.addEventListener('submit', async event => {
    event.preventDefault()
    if (button.disabled || !form.reportValidity()) return
    button.disabled = true
    button.textContent = 'Sending…'
    status.textContent = ''
    const fields = new FormData(form)
    try {
      const response = await fetch('/api/pool-requests', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: fields.get('topic'), description: fields.get('description'), email: fields.get('email') }),
      })
      const result = await response.json().catch(() => ({}))
      if (!response.ok || result.recorded !== true) throw new Error(result.error?.message || 'We could not save your request. Please try again.')
      form.reset()
      status.textContent = 'Request received. Thank you! We will review it and may follow up by email.'
      button.textContent = 'Request sent'
      status.focus()
    } catch (error) {
      status.textContent = error.message === 'Failed to fetch' ? 'Could not connect. Please try again or email info@shaduf.ai.' : error.message
      button.disabled = false
      button.textContent = 'Send request'
      status.focus()
    }
  })
})()
