import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatDividerModule } from '@angular/material/divider';

interface NavItem {
  icon: string;
  label: string;
  route: string;
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatListModule,
    MatIconModule,
    MatDividerModule
  ],
  template: `
    <div class="sidebar-header">
      <div class="logo-container">
        <mat-icon color="primary">computer</mat-icon>
        <span>Gestão de TI</span>
      </div>
    </div>
    
    <mat-divider></mat-divider>
    
    <mat-nav-list>
      <a mat-list-item *ngFor="let item of navItems" [routerLink]="item.route" routerLinkActive="active-link">
        <mat-icon matListItemIcon>{{ item.icon }}</mat-icon>
        <span matListItemTitle>{{ item.label }}</span>
      </a>
    </mat-nav-list>
  `,
  styles: [`
    .sidebar-header {
      height: 64px;
      display: flex;
      align-items: center;
      padding: 0 16px;
      
      .logo-container {
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 20px;
        font-weight: 500;
        
        mat-icon {
          transform: scale(1.2);
        }
      }
    }
    
    .active-link {
      background-color: rgba(63, 81, 181, 0.1);
      color: #3f51b5;
      
      mat-icon {
        color: #3f51b5;
      }
    }
  `]
})
export class SidebarComponent {
  navItems: NavItem[] = [
    { icon: 'dashboard', label: 'Dashboard', route: '/dashboard' },
    { icon: 'forum', label: 'Chamados', route: '/service-desk' },
    { icon: 'business', label: 'Unidades', route: '/organization' },
    { icon: 'account_tree', label: 'Setores', route: '/organization/sectors' },
    { icon: 'badge', label: 'Colaboradores', route: '/organization/employees' },
    { icon: 'people', label: 'Usuários', route: '/identity/users' },
    { icon: 'admin_panel_settings', label: 'Perfis (Roles)', route: '/identity/roles' },
  ];
}
