export const kpis = [
  { label: 'RUNS TODAY', value: '1,284', change: '+12.8%', key: 'runs' },
  { label: 'SUCCESS RATE', value: '99.2%', change: '+0.4%', key: 'success' },
  { label: 'HOURS SAVED', value: '186.5', change: '+18.3%', key: 'hours' },
  { label: 'COST AVOIDED', value: '$8,420', change: '+9.6%', key: 'cost' },
]

export const trendData = [
  { day: 'Mon', runs: 178, saved: 22 }, { day: 'Tue', runs: 205, saved: 29 },
  { day: 'Wed', runs: 192, saved: 26 }, { day: 'Thu', runs: 251, saved: 35 },
  { day: 'Fri', runs: 226, saved: 31 }, { day: 'Sat', runs: 147, saved: 19 },
  { day: 'Sun', runs: 85, saved: 12 },
]

export const workflows = [
  { name: 'Inbound lead follow-up', icon: '↗', trigger: 'New CRM contact', status: 'Active', lastRun: '2 min ago', runs: '248' },
  { name: 'Morning team brief', icon: '◷', trigger: 'Every weekday · 8:30 AM', status: 'Active', lastRun: 'Today, 8:30 AM', runs: '126' },
  { name: 'Support triage', icon: '⌘', trigger: 'New support message', status: 'Active', lastRun: '5 min ago', runs: '832' },
  { name: 'Weekly client pulse', icon: '⌁', trigger: 'Every Friday · 3:00 PM', status: 'Paused', lastRun: 'Nov 8, 3:00 PM', runs: '78' },
]

export const activity = [
  { title: 'New inquiry qualified', detail: 'Lead Follow-up · 2 minutes ago', state: 'success', duration: '1.4s', expanded: 'Matched company details, scored intent at 92%, and prepared a personalized reply for review.' },
  { title: 'Morning brief delivered', detail: 'Team Brief · 46 minutes ago', state: 'success', duration: '8.2s', expanded: 'Collected updates from 6 channels and sent the summary to #team-daily.' },
  { title: 'Calendar slot found', detail: 'Lead Follow-up · 1 hour ago', state: 'running', duration: 'working', expanded: 'Checking availability across the shared sales calendar.' },
  { title: 'Client record updated', detail: 'CRM Sync · 2 hours ago', state: 'error', duration: 'failed', expanded: 'The CRM returned a permission error. No changes were made. Check the integration connection to retry.' },
]
