import { ChangeDetectorRef, Component, DestroyRef, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterModule } from '@angular/router';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatDividerModule } from '@angular/material/divider';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AuthService } from '../../auth/auth.service';
import { OrganizationService } from '../../services/organization.service';

interface NavItem {
  icon: string;
  label: string;
  route: string;
  permission?: string;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatListModule,
    MatIconModule,
    MatDividerModule,
    MatTooltipModule
  ],
  template: `
    <div class="sidebar-header">
      <div class="logo-container">
        <img *ngIf="companyLogoUrl; else defaultLogo" [src]="companyLogoUrl" alt="Logo" class="company-logo" (error)="onLogoError()">
        <ng-template #defaultLogo>
          <div class="logo-badge">
            <mat-icon color="primary">computer</mat-icon>
          </div>
        </ng-template>
        <span class="company-name" [matTooltip]="companyName">{{ companyName }}</span>
      </div>
    </div>
    
    <mat-divider></mat-divider>
    
    <div class="nav-content">
      <ng-container *ngFor="let section of sections">
        <div class="nav-section" *ngIf="hasVisibleItems(section)">
          <div class="section-title">{{ section.title }}</div>
          <mat-nav-list dense>
            <ng-container *ngFor="let item of section.items">
              <a mat-list-item *ngIf="canAccess(item)" [routerLink]="item.route" routerLinkActive="active-link" [routerLinkActiveOptions]="{exact: item.route === '/dashboard' || item.route === '/organization'}">
                <mat-icon matListItemIcon>{{ item.icon }}</mat-icon>
                <span matListItemTitle>{{ item.label }}</span>
              </a>
            </ng-container>
          </mat-nav-list>
        </div>
      </ng-container>
    </div>
  `,
  styles: [`
    :host {
      display: flex;
      flex-direction: column;
      height: 100%;
    }

    .sidebar-header {
      height: 64px;
      display: flex;
      align-items: center;
      padding: 0 16px;
      background-color: #ffffff;
      
      .logo-container {
        display: flex;
        align-items: center;
        gap: 12px;
        overflow: hidden;

        .company-logo {
          max-height: 38px;
          max-width: 38px;
          object-fit: contain;
          border-radius: 6px;
        }

        .logo-badge {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 38px;
          height: 38px;
          background-color: #eff6ff;
          border-radius: 8px;

          mat-icon {
            font-size: 22px;
            width: 22px;
            height: 22px;
          }
        }
        
        .company-name {
          font-size: 16px;
          font-weight: 600;
          color: #1e293b;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      }
    }

    .nav-content {
      flex: 1;
      overflow-y: auto;
      padding: 12px 0 24px;
    }

    .nav-section {
      margin-bottom: 12px;

      .section-title {
        font-size: 11px;
        text-transform: uppercase;
        font-weight: 700;
        letter-spacing: 0.05em;
        color: #94a3b8;
        padding: 8px 16px 4px;
      }

      mat-nav-list {
        padding-top: 0;
      }

      a[mat-list-item] {
        margin: 2px 8px;
        border-radius: 8px;
        height: 40px;
        color: #475569;
        font-size: 13.5px;
        font-weight: 500;
        transition: all 0.15s ease-in-out;

        mat-icon {
          color: #64748b;
          font-size: 20px;
          width: 20px;
          height: 20px;
          margin-right: 12px;
        }

        &:hover {
          background-color: #f1f5f9;
          color: #1e293b;

          mat-icon {
            color: #1e293b;
          }
        }

        &.active-link {
          background-color: #eff6ff;
          color: #2563eb;
          font-weight: 600;

          mat-icon {
            color: #2563eb;
          }
        }
      }
    }
  `]
})
export class SidebarComponent implements OnInit {
  private authService = inject(AuthService);
  private orgService = inject(OrganizationService);
  private cdr = inject(ChangeDetectorRef);
  private destroyRef = inject(DestroyRef);

  companyName: string = 'Gestão de TI';
  companyLogoUrl: string | null = null;

  sections: NavSection[] = [
    {
      title: 'Principal',
      items: [
        { icon: 'dashboard', label: 'Dashboard', route: '/dashboard' }
      ]
    },
    {
      title: 'Notificações',
      items: [
        { icon: 'notifications', label: 'Caixa de entrada', route: '/notifications' },
        { icon: 'tune', label: 'Minhas preferências', route: '/notifications/preferences' },
        { icon: 'send', label: 'Entregas e regras', route: '/notifications/admin', permission: 'notifications.manage' }
      ]
    },
    {
      title: 'Service Desk',
      items: [
        { icon: 'forum', label: 'Chamados', route: '/service-desk' },
        { icon: 'add_circle', label: 'Abrir Chamado', route: '/service-desk/new' },
        { icon: 'category', label: 'Categorias de Chamados', route: '/service-desk/categories', permission: 'service_desk.tickets.manage' }
      ]
    },
    {
      title: 'Operações & Físico',
      items: [
        { icon: 'devices', label: 'Patrimônio & Ativos', route: '/assets', permission: 'assets.read' },
        { icon: 'upload_file', label: 'Importar Inventário (GLPI)', route: '/assets/import-glpi', permission: 'assets.write' },
        { icon: 'category', label: 'Categorias de Ativos', route: '/assets/categories', permission: 'assets.read' },
        { icon: 'inventory_2', label: 'Estoque & Insumos', route: '/stock', permission: 'stock.read' },
        { icon: 'category', label: 'Categorias de Estoque', route: '/stock/categories', permission: 'stock.read' },
        { icon: 'fact_check', label: 'Inventário Periódico', route: '/inventory', permission: 'inventory.read' }
      ]
    },
    {
      title: 'Organização',
      items: [
        { icon: 'domain', label: 'Empresa', route: '/organization/company', permission: 'organization.company.read' },
        { icon: 'business', label: 'Unidades', route: '/organization', permission: 'organization.units.read' },
        { icon: 'account_tree', label: 'Setores', route: '/organization/sectors', permission: 'organization.sectors.read' },
        { icon: 'badge', label: 'Colaboradores', route: '/organization/employees', permission: 'organization.employees.read' }
      ]
    },
    {
      title: 'Administração & Sistema',
      items: [
        { icon: 'settings_applications', label: 'Painel Administrativo', route: '/admin', permission: 'identity.roles.read' },
        { icon: 'history', label: 'Auditoria', route: '/audit', permission: 'audit.read' },
        { icon: 'people', label: 'Usuários', route: '/identity/users', permission: 'identity.users.read' },
        { icon: 'admin_panel_settings', label: 'Perfis (Roles)', route: '/identity/roles', permission: 'identity.roles.read' }
      ]
    }
  ];

  ngOnInit(): void {
    this.orgService.branding$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((branding) => {
      if (!branding) return;
      this.companyName = branding.name || 'Gestão de TI';
      this.companyLogoUrl = branding.logo_url;
      this.cdr.markForCheck();
    });
    this.orgService.loadBranding();
  }

  onLogoError(): void {
    this.companyLogoUrl = null;
  }

  canAccess(item: NavItem): boolean {
    if (!item.permission) return true;
    return this.authService.hasPermission(item.permission);
  }

  hasVisibleItems(section: NavSection): boolean {
    return section.items.some((item) => this.canAccess(item));
  }
}
