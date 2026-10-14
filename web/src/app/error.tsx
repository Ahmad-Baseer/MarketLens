"use client";

import { Empty } from "@/components/ui";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="mt-10">
      <Empty title="Something went wrong loading the data">
        The signal data couldn&apos;t be read just now.{" "}
        <button onClick={reset} className="font-medium text-brand underline">
          Try again
        </button>
      </Empty>
    </div>
  );
}
