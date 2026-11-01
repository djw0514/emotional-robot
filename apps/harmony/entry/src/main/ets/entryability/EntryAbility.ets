import { UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';

export default class EntryAbility extends UIAbility {
  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/Index').catch((error: Error): void => {
      console.error('Failed to load the companion page: ' + error.message);
    });
  }
}
