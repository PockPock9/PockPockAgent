// The planner's questions, one per page: pick a suggested answer or type your own, move with Back and
// Next, and send them all with the one Submit button on the last page. Questions left empty are not
// sent (the agent decides those). Closing keeps the plan; the card can open the dialog again.
import { ArrowLeft, ArrowRight, Check, LoaderCircle, MessageCircleQuestion } from 'lucide-react'
import { Modal } from './Modal'
import { choicesFor } from './PlanCard'

/** Answers typed so far and the page shown; kept by the plan card so closing the dialog loses nothing. */
export type QuestionsDraft = { page: number; answers: string[] }

export function QuestionsDialog({ questions, options, busy, error, draft, onDraft, onSubmit, onClose }: {
  questions: string[]
  options?: string[][]
  busy: boolean
  error?: string
  draft: QuestionsDraft
  onDraft: (draft: QuestionsDraft) => void
  onSubmit: (answers: { question: string; answer: string }[]) => void
  onClose: () => void
}) {
  const page = Math.min(draft.page, questions.length - 1)
  const answers = questions.map((_, index) => draft.answers[index] ?? '')
  const setPage = (next: number) => onDraft({ answers, page: next })
  const setAnswers = (change: (current: string[]) => string[]) => onDraft({ page, answers: change(answers) })
  const question = questions[page]
  const choices = choicesFor(question, options?.[page])
  const last = page === questions.length - 1
  const answered = answers.filter((answer) => answer.trim()).length
  const set = (value: string) => setAnswers((current) => current.map((answer, index) => (index === page ? value : answer)))
  const submit = () => onSubmit(questions.map((text, index) => ({ question: text, answer: answers[index] })).filter((item) => item.answer.trim()))
  const title = questions.length === 1 ? 'One question before it runs' : `${questions.length} questions before it runs`

  return (
    <Modal title={title} icon={<MessageCircleQuestion size={16} />} onClose={onClose}
      footer={
        <div className="questions__footer">
          <span className="note">{answered ? `${answered} of ${questions.length} answered. Empty answers are left to the agent.` : 'Empty answers are left to the agent.'}</span>
          <div className="card__actions">
            {page > 0 && <button type="button" className="button" disabled={busy} onClick={() => setPage(page - 1)}><ArrowLeft size={13} /> Back</button>}
            {last
              ? <button type="button" className="button button--primary" disabled={busy || !answered} onClick={submit}>{busy ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />} Submit answers</button>
              : <button type="button" className="button button--primary" onClick={() => setPage(page + 1)}>Next <ArrowRight size={13} /></button>}
          </div>
        </div>
      }>
      <form className="questions" onSubmit={(event) => { event.preventDefault(); if (last) { if (answered) submit() } else setPage(page + 1) }}>
        {questions.length > 1 && (
          <div className="questions__progress" aria-label={`Question ${page + 1} of ${questions.length}`}>
            {questions.map((_, index) => (
              <button key={index} type="button" className={`questions__dot${index === page ? ' is-current' : ''}${answers[index].trim() ? ' is-answered' : ''}`}
                aria-label={`Question ${index + 1}${answers[index].trim() ? ', answered' : ''}`} aria-current={index === page ? 'step' : undefined} onClick={() => setPage(index)} />
            ))}
            <span>Question {page + 1} of {questions.length}</span>
          </div>
        )}
        <p className="questions__text" id="question-text">{question}</p>
        {choices.length > 0 && (
          <div className="questions__choices" role="radiogroup" aria-labelledby="question-text">
            {choices.map((choice) => (
              <button key={choice} type="button" role="radio" aria-checked={answers[page] === choice} className={`button${answers[page] === choice ? ' is-pressed' : ''}`}
                onClick={() => set(answers[page] === choice ? '' : choice)}>{choice}</button>
            ))}
          </div>
        )}
        <input key={page} className="input" aria-label={`Your answer to: ${question}`} placeholder={choices.length ? 'Or type your own answer' : 'Type your answer'}
          value={choices.includes(answers[page]) ? '' : answers[page]} onChange={(event) => set(event.target.value)} />
        {error && <p className="card__error" role="alert">{error}</p>}
      </form>
    </Modal>
  )
}
