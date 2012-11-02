import os
import traceback

from direct.directtools.DirectGrid import DirectGrid
from wx.lib.pubsub import Publisher as pub
import pandac.PandaModules as pm
import panda3d.core as pc

import p3d
import wxExtra
import ui
import editor
import gizmos
import actions
import commands as cmds
from scene import Scene
from showBase import ShowBase
from selection import Selection
from project import Project
    

class App( p3d.wx.App ):
    
    """Base editor class."""
    
    def OnInit( self ):
        self.gizmo = False
        self._fooTask = None
        
        # Bind publisher events
        pub.subscribe( self.OnUpdate, 'Update' )
        pub.subscribe( self.OnUpdateSelection, 'UpdateSelection' )
        
        # Build main frame, start Panda and replace the wx event loop with
        # Panda's.
        self.frame = ui.MainFrame( None, size=(800, 600) )
        ShowBase( self.frame.pnlGameView, self.frame.pnlEdView )
        self.ReplaceEventLoop()
        
        # Create project manager
        self.project = Project( self )
        self.frame.SetProjectPath( self.frame.cfg.Read( 'projDirPath' ) )
        
        # Create grid
        self.grid = DirectGrid( 
            parent=base.edRender, 
            planeColor=(0.5, 0.5, 0.5, 0.5) 
        )
        
        # Create frame rate meter
        self.frameRate = p3d.FrameRate()
        
        # Create shading mode keys
        dsp = p3d.DisplayShading()
        dsp.accept( '4', dsp.Wireframe )
        dsp.accept( '5', dsp.Shade )
        dsp.accept( '6', dsp.Texture )
        
        # Set up gizmos
        self.SetupGizmoManager()
        
        # Bind mouse events
        self.accept( 'mouse1', self.OnMouse1Down )
        self.accept( 'shift-mouse1', self.OnMouse1Down, [True] )
        self.accept( 'mouse2', self.OnMouse2Down )
        self.accept( 'mouse1-up', self.OnMouse1Up )
        self.accept( 'mouse2-up', self.OnMouse2Up )
        
        # Create selection manager
        self.selection = Selection(
            camera=base.edCamera, 
            root2d=base.edRender2d, 
            win=base.edWin, 
            mouseWatcherNode=base.edMouseWatcherNode 
        )
        
        # Create actions manager which will control the undo queue.
        self.actnMgr = actions.Manager()
        
        # Bind events
        self.accept( 'z', self.actnMgr.Undo )
        self.accept( 'shift-z', self.actnMgr.Redo )
        self.accept( 'f', self.FrameSelection )
        self.accept( 'del', lambda fn: cmds.Remove( fn() ), [self.selection.Get] )
        self.accept( 'backspace', lambda fn: cmds.Remove( fn() ), [self.selection.Get] )
        self.accept( 'control-d', lambda fn: cmds.Duplicate( fn() ), [self.selection.Get] )
        self.accept( 'arrow_up', lambda fn: cmds.Select( fn() ), [self.selection.SelectParent] )
        self.accept( 'arrow_down', lambda fn: cmds.Select( fn() ), [self.selection.SelectChild] )
        self.accept( 'arrow_left', lambda fn: cmds.Select( fn() ), [self.selection.SelectPrev] )
        self.accept( 'arrow_right', lambda fn: cmds.Select( fn() ), [self.selection.SelectNext] )
        self.accept( 'projectFilesModified', self.OnProjectFilesModified )
        
        # DEBUG
        self.fileTypes = {
            '.egg':self.AddModel,
            '.bam':self.AddModel,
            '.pz':self.AddModel,
            '.sha':self.AddShader
        }
        
        # Create a "game"
        self.game = editor.Base()
        self.game.OnInit()
        
        # Start with a new scene
        self.CreateScene()
        self.doc.OnRefresh()
        
        self.frame.Show( True )
        
        return True
    
    def SetupGizmoManager( self ):
        """Create gizmo manager."""
        gizmoMgrRootNp = base.edRender.attachNewNode( 'gizmoManager' )
        kwargs = {
            'camera':base.edCamera, 
            'rootNp':gizmoMgrRootNp, 
            'win':base.edWin, 
            'mouseWatcherNode':base.edMouseWatcherNode
        }
        self.gizmoMgr = gizmos.Manager( **kwargs )
        self.gizmoMgr.AddGizmo( gizmos.Translation( 'pos', **kwargs ) )
        self.gizmoMgr.AddGizmo( gizmos.Rotation( 'rot', **kwargs ) )
        self.gizmoMgr.AddGizmo( gizmos.Scale( 'scl', **kwargs ) )
        
        # Bind gizmo manager events
        self.accept( 'q', self.gizmoMgr.SetActiveGizmo, [None] )
        self.accept( 'w', self.gizmoMgr.SetActiveGizmo, ['pos'] )
        self.accept( 'e', self.gizmoMgr.SetActiveGizmo, ['rot'] )
        self.accept( 'r', self.gizmoMgr.SetActiveGizmo, ['scl'] )
        self.accept( 'space', self.gizmoMgr.ToggleLocal )
        self.accept( '+', self.gizmoMgr.SetSize, [2] )
        self.accept( '-', self.gizmoMgr.SetSize, [0.5] )
        
    def OnMouse1Down( self, shift=False ):
        """
        Handle mouse button 1 down event. Start the drag select operation if
        a gizmo is not being used and the alt key is not down, otherwise start 
        the transform operation.
        """
        if ( not self.gizmoMgr.IsDragging() and 
             p3d.MOUSE_ALT not in base.edCamera.mouse.modifiers ):
            self.selection.StartDragSelect( shift )
        elif self.gizmoMgr.IsDragging():
            self.StartTransform()
            
    def OnMouse2Down( self ):
        """
        Handle mouse button 2 down event. Start the transform operation if a
        gizmo is being used.
        """
        if self.gizmoMgr.IsDragging():
            self.StartTransform()
                    
    def OnMouse1Up( self ):
        """
        Handle mouse button 1 up event. Stop the drag select operation if the
        marquee is running, otherwise stop the transform operation if a gizmo
        is being used.
        """
        if self.selection.marquee.IsRunning():
            
            # Don't perform selection if there are no nodes and the selection
            # is currently empty.
            selNodes = self.selection.StopDragSelect()
            if self.selection.nps or selNodes:
                cmds.Select( selNodes )
        elif self.gizmoMgr.IsDragging() or self.gizmo:
            self.StopTransform()
            
    def OnMouse2Up( self ):
        """
        Handle mouse button 2 up event. Stop the transform operation if a 
        gizmo is being used.
        """
        if self.gizmoMgr.IsDragging() or self.gizmo:
            self.StopTransform()
            
    def StartTransform( self ):
        """
        Start the transfrom operation by adding a task to constantly send a
        selection modified message while transfoming.
        """
        self._fooTask = taskMgr.add( self.doc.OnSelectionModified, 'SelectionModified' )
        self.gizmo = True
            
    def StopTransform( self ):
        """
        Stop the transfrom operation by removing the selection modified 
        message task. Also create a transform action and push it onto the undo 
        queue.
        """
        actGizmo = self.gizmoMgr.GetActiveGizmo()
        nps = actGizmo.attachedNps
        xforms = [np.getTransform() for np in nps]
        actn = actions.Transform( self, nps, xforms, actGizmo.initNpXforms )
        self.actnMgr.Push( actn )
        
        # Remove the transform task
        if self._fooTask in taskMgr.getAllTasks():
            taskMgr.remove( self._fooTask )
            self._fooTask = None
            
        self.gizmo = False
        self.doc.OnModified()
        
    def FrameSelection( self ):
        """
        Call frame selection on the camera if there are some node paths in the 
        selection.
        """
        if self.selection.nps:
            base.edCamera.Frame( self.selection.nps )
            
    def OnUpdate( self, msg ):
        self.selection.Update()
            
    def OnUpdateSelection( self, msg ):
        """
        Subscribed to the update selection message. Make sure that the
        selected nodes are attached to the managed gizmos, then refresh the
        active one.
        """
        self.gizmoMgr.AttachNodePaths( msg.data )
        self.gizmoMgr.RefreshActiveGizmo()
                    
    def CreateScene( self, filePath=None, newDoc=True ):
        """
        Create an empty scene and set its root node to the picker's root node.
        """
        # Reset undo queue if creating a new document
        if newDoc:
            self.actnMgr.Reset()
        
        # Close the current scene if there is one
        if hasattr( self, 'scene' ):
            self.game.pluginMgr.OnSceneClose()
            self.scene.Close()
            
        # Create a new scene
        self.scene = Scene( self, filePath=filePath, camera=base.edCamera )
        self.scene.rootNp.reparentTo( base.edRender )
        
        # Set the selection and picker root node to the scene's root node
        self.selection.rootNp = self.scene.rootNp
        self.selection.picker.rootNp = self.scene.rootNp
        self.selection.Clear()
        
        # Create the document wrapper if creating a new document
        if newDoc:
            self.doc = ui.Document( self.scene )
            self.doc.OnSelectionChanged()
        
    def OnDragDrop( self, filePath ):
        
        # Get the object under the mouse, if any
        np = self.selection.GetNodePathUnderMouse()
        self.AddFile( filePath, np )
        
    def AddFile( self, filePath, np=None ):
        ext = os.path.splitext( filePath )[1]
        if ext in self.fileTypes:
            fn = self.fileTypes[ext]
            fn( filePath, np )
                
    def AddModel( self, filePath, np=None ):
        np = base.game.nodeMgr.Create( 'ModelRoot', filePath )
        cmds.Add( [np] )
                
    def AddShader( self, filePath, np=None ):
        pandaPath = pm.Filename.fromOsSpecific( filePath )
        shdr = pc.Shader.load( pandaPath )
        
        # BROKEN
        self.SetAttribute( np.setShader, shdr, np.getShader(), np.clearShader )
        
    def OnProjectFilesModified( self, filePaths ):
        self.game.pluginMgr.OnProjectFilesModified( filePaths )