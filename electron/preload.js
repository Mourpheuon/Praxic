/**
 * 思悟 Agent —— Electron Preload 脚本
 *
 * 通过 contextBridge 安全地向渲染进程暴露精选的 Node.js API。
 * 当前版本（v0.0.1）保留为最小接口，后续可按需扩展：
 * - 原生文件对话框（dialog.showOpenDialog）
 * - 文件系统读写（fs.readFile / fs.writeFile）
 * - 系统通知（Notification）
 * - 自动更新（electron-updater）
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('siwu', {
    /** 平台信息 */
    platform: process.platform,

    /** Electron 版本 */
    electronVersion: process.versions.electron,

    /**
     * 打开原生文件选择对话框
     * @param {Object} options - { filters?: Array<{name: string, extensions: string[]}>, multiple?: boolean }
     * @returns {Promise<string[]>} 选中文件的绝对路径列表
     */
    selectFiles: async (options = {}) => {
        const { dialog } = require('electron');
        const result = await dialog.showOpenDialog({
            properties: ['openFile'],
            filters: options.filters || [
                { name: '所有支持的文件', extensions: ['pdf', 'docx', 'xlsx', 'pptx', 'txt', 'md', 'py', 'json', 'csv', 'html', 'js', 'ts', 'jsx', 'tsx', 'ipynb'] },
                { name: '所有文件', extensions: ['*'] },
            ],
        });
        return result.canceled ? [] : result.filePaths;
    },

    /**
     * 打开原生文件夹选择对话框（别名，与 pickFolder 等价）
     * @returns {Promise<string|null>} 选中文件夹的绝对路径，取消时返回 null
     */
    selectFolder: async () => {
        const { dialog } = require('electron');
        const result = await dialog.showOpenDialog({
            properties: ['openDirectory'],
        });
        return result.canceled ? null : result.filePaths[0];
    },

    /**
     * 打开原生文件夹选择对话框
     * @returns {Promise<string|null>} 选中文件夹的绝对路径，取消时返回 null
     */
    pickFolder: async () => {
        const { dialog } = require('electron');
        const result = await dialog.showOpenDialog({
            properties: ['openDirectory'],
            title: '选择项目文件夹',
        });
        return result.canceled ? null : result.filePaths[0];
    },

    /**
     * 向主进程发送消息（预留）
     */
    send: (channel, data) => {
        ipcRenderer.send(channel, data);
    },

    /**
     * 监听主进程消息（预留）
     */
    on: (channel, callback) => {
        ipcRenderer.on(channel, (event, ...args) => callback(...args));
    },
});
