import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatTabsModule } from '@angular/material/tabs';
import { ChannelsComponent } from './channels.component';
import { DeliveriesComponent } from './deliveries.component';
import { GatewaysComponent } from './gateways.component';
import { RulesComponent } from './rules.component';

@Component({
  selector: 'app-notifications-admin',
  standalone: true,
  imports: [MatTabsModule, RouterLink, DeliveriesComponent, RulesComponent, GatewaysComponent, ChannelsComponent],
  template: `
    <div class="page">
      <h1>Notificações — administração</h1>
      <p class="subtitle">Acompanhe entregas, ajuste as regras e veja a saúde dos canais e do worker.</p>
      <mat-tab-group animationDuration="0ms" mat-stretch-tabs="false">
        <mat-tab label="Entregas"><ng-template matTabContent><app-deliveries /></ng-template></mat-tab>
        <mat-tab label="Regras"><ng-template matTabContent><app-rules /></ng-template></mat-tab>
        <mat-tab label="Gateways"><ng-template matTabContent><app-gateways /></ng-template></mat-tab>
        <mat-tab label="Saúde dos canais">
          <ng-template matTabContent>
            <p class="channels-link" data-testid="channels-link">
              Para configurar WhatsApp, Telegram, Slack ou e-mail, use <a routerLink="/channels">Canais de comunicação</a>.
            </p>
            <app-channels />
          </ng-template>
        </mat-tab>
      </mat-tab-group>
    </div>
  `,
  styles: [`
    .page { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
    h1 { margin: 0; font-size: 24px; }
    .subtitle { margin: 4px 0 16px; color: #64748b; }
    .channels-link { margin: 16px 0 0; font-size: 13px; color: #475569; }
  `]
})
export class NotificationsAdminComponent {}
