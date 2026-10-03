import {SerialCommandQueue} from "../src/serial-command-queue";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

(async () => {
  const queue = new SerialCommandQueue();
  const order: string[] = [];
  let releaseFirst!: () => void;
  const firstGate = new Promise<void>(resolve => {
    releaseFirst = resolve;
  });

  const first = queue.run(async () => {
    order.push("first:start");
    await firstGate;
    order.push("first:end");
    return 1;
  });

  const second = queue.run(async () => {
    order.push("second:start");
    order.push("second:end");
    return 2;
  });

  await Promise.resolve();
  assert(
    order.join(",") === "first:start",
    "second command started before first completed"
  );

  releaseFirst();
  const values = await Promise.all([first, second]);
  assert(values.join(",") === "1,2", "queue changed command results");
  assert(
    order.join(",") ===
      "first:start,first:end,second:start,second:end",
    "commands were not serialized"
  );

  const failed = queue.run(async () => {
    order.push("failed");
    throw new Error("expected");
  });
  await failed.catch(() => undefined);

  const afterFailure = await queue.run(async () => {
    order.push("after-failure");
    return 3;
  });
  assert(afterFailure === 3, "failed command poisoned the queue");

  console.log("clean-room serial command queue: PASS");
})().catch(error => {
  console.error(error);
  throw error;
});
