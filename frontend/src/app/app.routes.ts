import { Routes } from '@angular/router';
import { LoginComponent } from './features/auth/login/login.component';
import { ShellComponent } from './core/layout/shell/shell.component';
import { setupGuard } from './core/auth/setup.guard';
import { authGuard, guestGuard, permissionGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: 'setup',
    loadComponent: () => import('./features/setup/setup.component').then(m => m.SetupComponent),
    canActivate: [setupGuard]
  },
  {
    path: 'login',
    component: LoginComponent,
    canActivate: [guestGuard]
  },
  {
    path: 'change-password',
    loadComponent: () => import('./features/auth/change-password/change-password.component').then(m => m.ChangePasswordComponent),
    canActivate: [authGuard]
  },
  {
    path: '',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      {
        path: '',
        redirectTo: 'dashboard',
        pathMatch: 'full'
      },
      {
        path: 'dashboard',
        loadComponent: () => import('./features/dashboard/dashboard.component').then(m => m.Dashboard)
      },
      {
        path: 'organization',
        canActivate: [permissionGuard('organization.units.read')],
        loadComponent: () => import('./features/organization/unit-list/unit-list.component').then(m => m.UnitList)
      },
      {
        path: 'organization/sectors',
        canActivate: [permissionGuard('organization.sectors.read')],
        loadComponent: () => import('./features/organization/sector-list/sector-list.component').then(m => m.SectorList)
      },
      {
        path: 'organization/employees',
        canActivate: [permissionGuard('organization.employees.read')],
        loadComponent: () => import('./features/organization/employee-list/employee-list.component').then(m => m.EmployeeList)
      },
      {
        path: 'identity/users',
        canActivate: [permissionGuard('identity.users.read')],
        loadComponent: () => import('./features/identity/user-list/user-list.component').then(m => m.UserList)
      },
      {
        path: 'identity/roles',
        canActivate: [permissionGuard('identity.roles.read')],
        loadComponent: () => import('./features/identity/role-list/role-list.component').then(m => m.RoleList)
      },
      {
        path: 'admin',
        canActivate: [permissionGuard('identity.roles.read')],
        loadComponent: () => import('./features/admin/admin.component').then(m => m.AdminComponent)
      },
      {
        path: 'notifications',
        loadComponent: () => import('./features/notifications/inbox/inbox.component').then(m => m.InboxComponent)
      },
      {
        path: 'notifications/preferences',
        loadComponent: () => import('./features/notifications/preferences/preferences.component').then(m => m.PreferencesComponent)
      },
      {
        path: 'notifications/admin',
        canActivate: [permissionGuard('notifications.manage')],
        loadComponent: () => import('./features/notifications/admin/notifications-admin.component').then(m => m.NotificationsAdminComponent)
      },
      {
        path: 'service-desk',
        loadComponent: () => import('./features/service-desk/ticket-list/ticket-list.component').then(m => m.TicketListComponent)
      },
      {
        path: 'service-desk/categories',
        canActivate: [permissionGuard('service_desk.tickets.manage')],
        loadComponent: () => import('./features/service-desk/category-list/category-list.component').then(m => m.CategoryListComponent)
      },
      {
        path: 'service-desk/new',
        loadComponent: () => import('./features/service-desk/ticket-create/ticket-create.component').then(m => m.TicketCreateComponent)
      },
      {
        path: 'service-desk/:id',
        loadComponent: () => import('./features/service-desk/ticket-detail/ticket-detail.component').then(m => m.TicketDetailComponent)
      },
      {
        path: 'assets',
        canActivate: [permissionGuard('assets.read')],
        loadComponent: () => import('./features/assets/asset-list/asset-list.component').then(m => m.AssetListComponent)
      },
      {
        path: 'assets/categories',
        canActivate: [permissionGuard('assets.read')],
        loadComponent: () => import('./features/assets/category-list/category-list.component').then(m => m.AssetCategoryListComponent)
      },
      {
        path: 'assets/new',
        canActivate: [permissionGuard('assets.write')],
        loadComponent: () => import('./features/assets/asset-create/asset-create.component').then(m => m.AssetCreateComponent)
      },
      {
        path: 'assets/import-glpi',
        canActivate: [permissionGuard('assets.write')],
        loadComponent: () => import('./features/assets/asset-glpi-import/asset-glpi-import.component').then(m => m.AssetGlpiImportComponent)
      },
      {
        path: 'assets/:id',
        canActivate: [permissionGuard('assets.read')],
        loadComponent: () => import('./features/assets/asset-detail/asset-detail.component').then(m => m.AssetDetailComponent)
      },
      {
        path: 'stock',
        canActivate: [permissionGuard('stock.read')],
        loadComponent: () => import('./features/stock/stock-list/stock-list.component').then(m => m.StockListComponent)
      },
      {
        path: 'stock/categories',
        canActivate: [permissionGuard('stock.read')],
        loadComponent: () => import('./features/stock/category-list/category-list.component').then(m => m.StockCategoryListComponent)
      },
      {
        path: 'stock/new',
        canActivate: [permissionGuard('stock.write')],
        loadComponent: () => import('./features/stock/stock-create/stock-create.component').then(m => m.StockCreateComponent)
      },
      {
        path: 'stock/:id',
        canActivate: [permissionGuard('stock.read')],
        loadComponent: () => import('./features/stock/stock-detail/stock-detail.component').then(m => m.StockDetailComponent)
      },
      {
        path: 'inventory',
        canActivate: [permissionGuard('inventory.read')],
        loadComponent: () => import('./features/inventory/inventory-list/inventory-list.component').then(m => m.InventoryListComponent)
      },
      {
        path: 'inventory/:id',
        canActivate: [permissionGuard('inventory.read')],
        loadComponent: () => import('./features/inventory/inventory-detail/inventory-detail.component').then(m => m.InventoryDetailComponent)
      }
    ]
  },
  {
    path: '**',
    redirectTo: ''
  }
];
