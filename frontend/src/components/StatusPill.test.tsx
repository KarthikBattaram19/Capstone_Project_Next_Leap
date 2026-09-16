import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusPill } from "./StatusPill";

describe("status pill before the renter taps", () => {
  it("never says 'Not connected' when the service answered its health check", () => {
    const { container } = render(<StatusPill connection="closed" started={false} service="up" />);
    expect(container.textContent).toBe("Service ready");
    expect(container.firstElementChild?.className).toContain("status--ok");
  });

  it("says the service is unreachable when the health check failed", () => {
    const { container } = render(<StatusPill connection="closed" started={false} service="down" />);
    expect(container.textContent).toBe("Can't reach the service");
    expect(container.firstElementChild?.className).toContain("status--bad");
  });

  it("shows a neutral checking state while the health check is in flight", () => {
    const { container } = render(<StatusPill connection="closed" started={false} service="checking" />);
    expect(container.textContent).toBe("Checking service…");
    expect(container.firstElementChild?.className).toContain("status--wait");
  });

  it("reports the live socket, not the health check, once a session has started", () => {
    const { container } = render(<StatusPill connection="open" started={true} service="down" />);
    expect(container.textContent).toBe("Connected");
  });
});
