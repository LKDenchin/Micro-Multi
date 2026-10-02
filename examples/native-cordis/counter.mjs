import { Service } from '@deepseek-ai/cordis';
export default class Counter extends Service {
 constructor(ctx,config) { super(ctx,'nativeCounter'); this.value=config.start??0; }
 next() { this.ctx.emit('native-example/tick',++this.value); return this.value; }
}
