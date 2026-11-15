export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

export function modelFamily(name: string) {
  if (name.includes('embed')) return 'Embedding'
  if (name.includes('llava')) return 'Vision'
  if (name.includes('coder')) return 'Code'
  if (name.includes('deepseek') || name.includes('r1')) return 'Reasoning'
  if (name.includes('mistral-nemo')) return 'Agent'
  return 'General'
}
