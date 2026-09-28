(function(root) {
  'use strict'
  function tagLabel(value) { return typeof value === 'string' ? value.normalize('NFC').trim().replace(/\s+/gu, ' ') : '' }
  function tagKey(value) { return tagLabel(value).toLowerCase() }
  const api = { tagKey, tagLabel }
  root.ShadufDiscovery = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})(globalThis)
