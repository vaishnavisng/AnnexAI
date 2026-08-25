"use client";

export default function FlashStack({ messages }: { messages: { type: string; text: string }[] }) {
  if (!messages.length) return null;
  return (
    <div className="flash-stack">
      {messages.map((msg, i) => (
        <div key={i} className={`flash flash-${msg.type}`}>{msg.text}</div>
      ))}
    </div>
  );
}
