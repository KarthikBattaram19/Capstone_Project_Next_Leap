import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";
import { FailureBanner } from "./FailureBanner";

const classes = (c: HTMLElement) =>
  new Set(Array.from(c.querySelectorAll("*")).flatMap((n) => Array.from(n.classList)));

describe("failure vs empty", () => {
  it("never share a class", () => {
    const f = render(
      <FailureBanner
        failure={{ capability: "understanding", tell_renter: "x", retry_worth_it: true }}
        onRetry={() => {}}
      />,
    );
    const e = render(
      <EmptyState
        result={{
          unmet: [{ field: "rent_max", value: "25000", binding: true }],
          suggestions: ["try ₹30,000"],
          spoken: "",
        }}
      />,
    );
    const shared = [...classes(f.container)].filter((c) => classes(e.container).has(c));
    expect(shared).toEqual([]);
    expect(f.container.textContent).toContain("understanding");
    expect(e.container.textContent).toContain("won't relax");
  });

  it("names the capability in words and offers Retry only when worth it", () => {
    const f = render(
      <FailureBanner
        failure={{ capability: "speech_out", tell_renter: "Voice is down.", retry_worth_it: false }}
        onRetry={() => {}}
      />,
    );
    expect(f.container.textContent).toContain("voice output");
    expect(f.container.textContent).toContain("Voice is down.");
    expect(f.container.querySelector("button")).toBeNull();
  });
});
