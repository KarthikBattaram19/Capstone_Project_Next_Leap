import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Unmount every rendered tree between tests, or one test's DOM leaks into the next.
afterEach(() => cleanup());
