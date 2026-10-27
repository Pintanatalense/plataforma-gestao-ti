import { Component, inject } from '@angular/core';
import { MatTabsModule } from '@angular/material/tabs';
import { AuthService } from '../../../core/auth/auth.service';
import { MessageComposeComponent } from './compose.component';
import { MessageHistoryComponent } from './history.component';
import { MessageSchedulesComponent } from './schedules.component';
import { MessageTemplatesComponent } from './templates.component';

@Component({
  selector: 'app-messages-page',
  standalone: true,
  imports: [MatTabsModule, MessageComposeComponent, MessageHistoryComponent, MessageSchedulesComponent, MessageTemplatesComponent],
  template: `
    <div class="page">
      <h1>Central de mensagens</h1>
      <p class="subtitle">Envie avisos a pessoas escolhidas pelo canal que elas vincularam e acompanhe cada entrega.</p>
      <mat-tab-group animationDuration="0ms" mat-stretch-tabs="false">
        @if (canSend) {
          <mat-tab label="Nova mensagem"><ng-template matTabContent><app-message-compose [canSchedule]="canSchedule" /></ng-template></mat-tab>
        }
        @if (canSend || canRead || canManage) {
          <mat-tab label="Histórico"><ng-template matTabContent><app-message-history /></ng-template></mat-tab>
        }
        @if (canSchedule || canRead || canManage) {
          <mat-tab label="Agendamentos"><ng-template matTabContent><app-message-schedules /></ng-template></mat-tab>
        }
        @if (canManage) {
          <mat-tab label="Modelos"><ng-template matTabContent><app-message-templates /></ng-template></mat-tab>
        }
      </mat-tab-group>
    </div>
  `,
  styles: [`
    .page { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
    h1 { margin: 0; font-size: 24px; }
    .subtitle { margin: 4px 0 16px; color: #64748b; }
  `]
})
export class MessagesPageComponent {
  private auth = inject(AuthService);
  readonly canSend = this.auth.hasPermission('notifications.messages.send');
  readonly canRead = this.auth.hasPermission('notifications.messages.read');
  readonly canManage = this.auth.hasPermission('notifications.manage');
  // agendar usa a busca de pessoas e a prévia do envio: precisa também de "Enviar mensagens"
  readonly canSchedule = this.auth.hasPermission('notifications.messages.schedule');
}
