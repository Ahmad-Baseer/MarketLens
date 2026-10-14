import Link from "next/link";
import { Empty } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="mt-10">
      <Empty title="Page not found">
        That signal or page doesn&apos;t exist.{" "}
        <Link href="/" className="font-medium text-brand underline">
          Back to today&apos;s signals
        </Link>
      </Empty>
    </div>
  );
}
