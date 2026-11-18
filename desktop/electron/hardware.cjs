// Hardware check for setup: memory, graphics card and free disk space, and the model that fits.
// Used to pick a default model a non-technical user does not have to choose, and to stop setup
// before a download fills the disk.
const fs = require('node:fs')
const os = require('node:os')
const paths = require('./paths.cjs')
const { run } = require('./platform.cjs')

/** Default-model choices, smallest first. Sizes are Ollama's download sizes. */
const MODEL_CHOICES = [
  { name: 'qwen3.5:4b', downloadGB: 3.4, summary: 'Smaller and quicker. Works on most computers.' },
  { name: 'qwen3.5:9b', downloadGB: 6.6, summary: 'Better answers. Needs a graphics card with 8 GB of memory, or an Apple silicon Mac with 16 GB.' },
  { name: 'qwen3.5:27b', downloadGB: 17, summary: 'Best answers, but slow unless the graphics card has 20 GB of memory or more.' },
]
const ROUTER_MODEL_GB = 2.7 // qwen3.5:2b (2.0 GB weights + 0.7 GB vision projector)

/** Approximate downloads per component, in GB (the model is counted separately). */
const COMPONENT_GB = { core: 0.7, ollama: 1.2, openclaw: 0.4, nemoclaw: 8 }

const round = (value) => Math.round(value * 10) / 10

/** NVIDIA cards through nvidia-smi on Windows; Apple silicon shares system memory. Null if none found. */
async function detectGpu(ramGB) {
  if (paths.IS_MAC) return os.arch() === 'arm64' ? { name: 'Apple silicon', memoryGB: ramGB, shared: true } : null
  const result = await run('nvidia-smi', ['--query-gpu=name,memory.total', '--format=csv,noheader,nounits'], { timeout: 15000 })
  if (!result.ok) return null
  const cards = result.stdout.split(/\r?\n/).map((line) => line.split(',').map((part) => part.trim())).filter(([name, memory]) => name && Number(memory) > 0)
  if (!cards.length) return null
  const [name, memoryMiB] = cards.sort((a, b) => Number(b[1]) - Number(a[1]))[0]
  return { name, memoryGB: round(Number(memoryMiB) / 1024), shared: false }
}

/** Free space on the drive that holds the user's folder (models and PockPock's runtime live there). */
function freeDiskGB() {
  try {
    const stats = fs.statfsSync(os.homedir())
    return round((stats.bavail * stats.bsize) / 1e9)
  } catch {
    return null
  }
}

async function detect() {
  const ramGB = round(os.totalmem() / 1024 ** 3)
  return { ramGB, gpu: await detectGpu(ramGB), freeDiskGB: freeDiskGB(), cpu: os.cpus()[0]?.model?.trim() || '' }
}

/** The default model for this computer, with a plain-language reason. A model that is already
 * downloaded is kept, so setup never downloads a second one the user does not need. */
function recommendModel(hardware, installed = []) {
  const has = (name) => installed.some((item) => item === name || item === `${name}:latest`)
  if (has('qwen3.5:9b')) return { name: 'qwen3.5:9b', reason: 'Already downloaded on this computer.' }
  if (has('qwen3.5:4b')) return { name: 'qwen3.5:4b', reason: 'Already downloaded on this computer.' }
  const { gpu, ramGB } = hardware
  if (gpu && !gpu.shared && gpu.memoryGB >= 8) return { name: 'qwen3.5:9b', reason: `Your graphics card (${gpu.name}, ${gpu.memoryGB} GB) runs it quickly.` }
  if (gpu?.shared && ramGB >= 16) return { name: 'qwen3.5:9b', reason: `Your Mac has ${ramGB} GB of memory, enough to run it quickly.` }
  if (gpu?.shared) return { name: 'qwen3.5:4b', reason: `Your Mac has ${ramGB} GB of memory; the larger model would be slow.` }
  if (gpu) return { name: 'qwen3.5:4b', reason: `Your graphics card has ${gpu.memoryGB} GB of memory; the larger model would be slow.` }
  return { name: 'qwen3.5:4b', reason: 'No suitable graphics card was found, so a smaller model keeps replies quick.' }
}

/** Download size and the free space setup needs, in GB, for the components not yet installed.
 * The space allows for installers being unpacked and a little room to spare. */
function estimate(components, model, missing) {
  const modelGB = MODEL_CHOICES.find((item) => item.name === model)?.downloadGB ?? 6.6
  let downloadGB = 0
  for (const component of components) {
    if (component === 'ollama') {
      // Ollama may already be installed while the models are still missing, or the other way round.
      if (missing.includes('ollama')) downloadGB += COMPONENT_GB.ollama
      if (missing.includes('model')) downloadGB += modelGB
      if (missing.includes('router')) downloadGB += ROUTER_MODEL_GB
    } else if (missing.includes(component)) {
      downloadGB += COMPONENT_GB[component] ?? 0
    }
  }
  downloadGB = round(downloadGB)
  return { downloadGB, neededGB: downloadGB ? round(downloadGB * 1.5 + 2) : 0 }
}

module.exports = { MODEL_CHOICES, detect, recommendModel, estimate }
