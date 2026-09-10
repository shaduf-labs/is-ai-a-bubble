document.querySelector('[data-dynamic-logout]')?.addEventListener('click', async () => {
  const session = await fetch('/api/session').then((response) => response.json())
  const response = await fetch('/api/auth/logout', { method: 'POST', headers: { 'x-shaduf-csrf': session.csrf_token || '' } })
  if (response.ok) location.href = '/'
})
