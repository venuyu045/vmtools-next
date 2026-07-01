import { defineStore } from 'pinia'

export interface DevLogEntry {
  ts: number
  tag: string
  msg: string
  level: 'info' | 'warn' | 'error'
}

export const useDevLogStore = defineStore('devLog', {
  state: () => ({
    logs: [] as DevLogEntry[],
  }),
  actions: {
    log(tag: string, msg: string, level: 'info' | 'warn' | 'error' = 'info') {
      this.logs.push({ ts: Date.now(), tag, msg, level })
      if (this.logs.length > 500) {
        this.logs = this.logs.slice(-300)
      }
    },
    clear() {
      this.logs = []
    },
  },
})
