// Test-only driver. Never included in the production XPI.
export class AssistantAcceptanceChild extends JSWindowActorChild {
  receiveMessage(message) {
    if(message.name!=='run')throw new Error('UNKNOWN_TEST_MESSAGE');
    return new Function('document','args',message.data.script)(this.document,message.data.args);
  }
}
