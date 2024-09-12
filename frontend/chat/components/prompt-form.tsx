'use client'

import * as React from 'react'
import Textarea from 'react-textarea-autosize'
import { useRouter } from 'next/navigation'
import { nanoid } from 'nanoid'

import { useActions, useUIState } from 'ai/rsc'
import { UserMessage, BotMessage } from './stocks/message'
import { type AI } from '@/lib/chat/actions'
import { Button } from '@/components/ui/button'
import { IconArrowElbow, IconPlus } from '@/components/ui/icons'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip'
import { useEnterSubmit } from '@/lib/hooks/use-enter-submit'

export function PromptForm({
  input,
  setInput,
}: {
  input: string
  setInput: (value: string) => void
}) {
  const router = useRouter()
  const { formRef, onKeyDown } = useEnterSubmit()
  const inputRef = React.useRef<HTMLTextAreaElement>(null)
  const { submitUserMessage } = useActions()
  const [messages, setMessages] = useUIState<typeof AI>()
  const [socket, setSocket] = React.useState<WebSocket | null>(null)

  React.useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus()
    }

    // Initialize WebSocket connection
    const ws = new WebSocket('ws://localhost:8000/ws')
    setSocket(ws)

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      switch (data.type) {
        case 'queries':
          setMessages(currentMessages => [
            ...currentMessages,
            {
              id: nanoid(),
              display: <BotMessage content={`Queries:\n${data.data.join('\n')}`} />
            }
          ])
          break
        case 'statements':
          setMessages(currentMessages => [
            ...currentMessages,
            {
              id: nanoid(),
              display: <BotMessage content={`Statements:\n${data.data.map((stmt: any) => `${stmt.id}: ${stmt.text}`).join('\n')}`} />
            }
          ])
          break
        case 'answer':
        case 'final_answer':
          setMessages(currentMessages => [
            ...currentMessages,
            {
              id: nanoid(),
              display: <BotMessage content={data.data} />
            }
          ])
          break
      }
    }

    return () => {
      ws.close()
    }
  }, [])

  return (
    <form
      ref={formRef}
      onSubmit={async (e: any) => {
        e.preventDefault()

        if (window.innerWidth < 600) {
          e.target['message']?.blur()
        }

        const value = input.trim()
        setInput('')
        if (!value) return

        setMessages(currentMessages => [
          ...currentMessages,
          {
            id: nanoid(),
            display: <UserMessage>{value}</UserMessage>
          }
        ])

        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({
            question: value,
            iterations: 1,
            num_queries: 3
          }))
        } else {
          console.error('WebSocket is not connected')
          setMessages(currentMessages => [
            ...currentMessages,
            {
              id: nanoid(),
              display: <BotMessage content="Sorry, I'm having trouble connecting to the server. Please try again later." />
            }
          ])
        }
      }}
    >
      <div className="relative flex max-h-60 w-full grow flex-col overflow-hidden bg-background px-8 sm:rounded-md sm:border sm:px-12">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              className="absolute left-0 top-[14px] size-8 rounded-full bg-background p-0 sm:left-4"
              onClick={() => {
                router.push('/new')
              }}
            >
              <IconPlus />
              <span className="sr-only">New Chat</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>New Chat</TooltipContent>
        </Tooltip>
        <Textarea
          ref={inputRef}
          tabIndex={0}
          onKeyDown={onKeyDown}
          placeholder="Send a message."
          className="min-h-[60px] w-full resize-none bg-transparent px-4 py-[1.3rem] focus-within:outline-none sm:text-sm"
          autoFocus
          spellCheck={false}
          autoComplete="off"
          autoCorrect="off"
          name="message"
          rows={1}
          value={input}
          onChange={e => setInput(e.target.value)}
        />
        <div className="absolute right-0 top-[13px] sm:right-4">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button type="submit" size="icon" disabled={input === ''}>
                <IconArrowElbow />
                <span className="sr-only">Send message</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>Send message</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </form>
  )
}
