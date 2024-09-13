import { toast } from 'sonner'
import { AIMessage } from './types'
import { generateId } from 'ai'

export class WebSocketService {
  private socket: WebSocket | null = null
  private messageQueue: string[] = []
  private isConnected = false
  private messageHandler: (message: AIMessage) => void = () => {}

  constructor(private url: string) {}

  connect() {
    this.socket = new WebSocket(this.url)

    this.socket.onopen = () => {
      console.log('WebSocket connected')
      this.isConnected = true
      this.processQueue()
    }

    this.socket.onmessage = (event) => {
      const data = JSON.parse(event.data)
      this.handleMessage(data)
    }

    this.socket.onerror = (error) => {
      console.error('WebSocket error:', error)
      toast.error('WebSocket error occurred')
    }

    this.socket.onclose = () => {
      console.log('WebSocket disconnected')
      this.isConnected = false
      toast.error('WebSocket disconnected')
    }
  }

  sendMessage(message: string) {
    if (this.isConnected && this.socket) {
      this.socket.send(message)
    } else {
      this.messageQueue.push(message)
    }
  }

  setMessageHandler(handler: (message: AIMessage) => void) {
    this.messageHandler = handler
  }

  private processQueue() {
    while (this.messageQueue.length > 0) {
      const message = this.messageQueue.shift()
      if (message) this.sendMessage(message)
    }
  }

  private handleMessage(data: any) {
    let message: AIMessage | null = null

    switch (data.type) {
      case 'queries':
        message = {
          id: generateId(),
          role: 'assistant',
          content: JSON.stringify(data.data),
          type: 'related'
        }
        break
      case 'statements':
        message = {
          id: generateId(),
          role: 'assistant',
          content: JSON.stringify(data.data),
          type: 'tool',
          name: 'search'
        }
        break
      case 'answer':
      case 'final_answer':
        message = {
          id: generateId(),
          role: 'assistant',
          content: data.data,
          type: 'answer'
        }
        break
      default:
        console.warn('Unknown message type:', data.type)
        return
    }

    if (message) {
      this.messageHandler(message)
    }
  }

  disconnect() {
    if (this.socket) {
      this.socket.close()
    }
  }
}