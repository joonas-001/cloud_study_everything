import { writeFileSync } from "node:fs";

import type { FullResult, Reporter } from "@playwright/test/reporter";

interface CompletionReporterOptions {
  outputFile: string;
}

export default class CompletionReporter implements Reporter {
  constructor(private readonly options: CompletionReporterOptions) {}

  onEnd(result: FullResult): void {
    writeFileSync(
      this.options.outputFile,
      JSON.stringify({ status: result.status }),
      "utf8",
    );
  }
}
